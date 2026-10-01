#!/usr/bin/env bash
# Build the Ben 10 Omniverse native macOS/arm64 host.
#
# Generic subset of games/gow2/build_macos.sh: lifted chunks + runtime PPU
# sources + generated HLE NID table + boot host + link against
# libps3recomp_runtime.a. No game-specific host code, hooks or SPU images yet.
#
# Assumes the lift already ran:
#   python3 ../ps3recomp/tools/ppu_lifter.py EBOOT.ELF --functions functions.json -o recomp_macos -j 8
# The 60 fps plan's lift (mid-asm hooks declared in recomp.toml; bodies in host/ben10_framestep_hook.cpp,
# no-ops without PS3_BEN10_FPS) is the same command plus --config and another output directory:
#   python3 ../ps3recomp/tools/ppu_lifter.py EBOOT.ELF --functions functions.json -o recomp_macos_fs -j 6 \
#       --config recomp.toml          (recomp.toml [main].out_directory = recomp_macos_fs)
#   ./build_macos.sh recomp_macos_fs
# Lifter drift gate (2026-09-30, ps3recomp 5ce9f15d): the same command WITHOUT --config reproduces
# recomp_macos/ppu_recomp_*.cpp byte for byte except the `/* lifter-rev: ... */` comment line (the old lift
# says 92c69cee-dirty), and the hooked lift = the unhooked one + 7 `gow2_midasm_Ben10*(ctx);` call lines
# (4 declared EAs) + a declaration block per chunk (chunk boundaries shift by those lines).
# and the runtime library is current (this script does NOT rebuild it):
#   cmake --build ../ps3recomp/build-macos
#
# Usage: ./build_macos.sh [lift-dir]        (default: recomp_macos)
#   LIFT_OPT=-O0..-O3 (default -O1)  HOST_OPT (default -O2)  OUT (default ./boot_ben10)
#   FORCE_REBUILD_LIFT=1  rebuild every lift chunk
#   LIFT_CFLAGS='...'  extra flags for lift chunks and lifted SPU jobs (PGO use: -fprofile-use=F)
#   HOST_CFLAGS='...'  extra flags for runtime PPU sources (PGO gen: -DPS3_PGO_BUILD)
#   LINK_CFLAGS='...'  extra flags on the final link (PGO gen: -fprofile-generate)
#   LIFT_OBJ_TAG=tag   extra object suffix so PGO gen/use objects coexist with plain ones
#
# PGO (same recipe as games/gow2/build_macos.sh; measured NEUTRAL in fps on GoW2):
#   1. LIFT_OBJ_TAG=pgogen LIFT_CFLAGS=-fprofile-generate HOST_CFLAGS=-DPS3_PGO_BUILD \
#      LINK_CFLAGS=-fprofile-generate OUT=./boot_ben10_pgogen ./build_macos.sh
#   2. BOOT_BIN=./boot_ben10_pgogen LLVM_PROFILE_FILE=pgo/ben10-%p.profraw PS3_PGO_WRITE_MS=60000 \
#      ./run_ben10.sh   (the writer dumps the profile while the game runs; runs end in kill -9)
#   3. xcrun llvm-profdata merge -o pgo/ben10.profdata pgo/*.profraw
#   4. LIFT_OBJ_TAG=pgo LIFT_CFLAGS=-fprofile-use=$PWD/pgo/ben10.profdata ./build_macos.sh
#
# host/*.c (except test_*.c) are the port's own pure host units (e.g. host/ben10_framestep.c, the
# frame-step policy of the 60 fps plan); they are compiled and linked into the binary.
# Unit tests: clang -std=c11 -Wall -Wextra -Ihost host/test_ben10_framestep.c host/ben10_framestep.c -lm
#
# NB: OUT must not contain "boot_gow2" -- the GoW2 tooling kills any process
# with that in its name.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PS3="${PS3_ENGINE_ROOT:-$HERE/../ps3recomp}"
PYBIN="${PY:-$PS3/.venv/bin/python}"
[ -x "$PYBIN" ] || PYBIN="$(command -v python3)"
if [ "$(uname -s)" = "Darwin" ] && [ -z "${SDKROOT:-}" ]; then
    SDKROOT="$(xcrun --show-sdk-path)"
    export SDKROOT
fi

LIFT="${1:-$HERE/recomp_macos}"
OUT="${OUT:-$HERE/boot_ben10}"
LIFT_OPT="${LIFT_OPT:--O1}"
HOST_OPT="${HOST_OPT:--O2}"
MCPU="${PS3_MCPU--mcpu=apple-m1}"
FORCE_REBUILD_LIFT="${FORCE_REBUILD_LIFT:-0}"
LIFT_CFLAGS="${LIFT_CFLAGS:-}"
HOST_CFLAGS="${HOST_CFLAGS:-}"
LINK_CFLAGS="${LINK_CFLAGS:-}"
LIFT_OBJ_TAG="${LIFT_OBJ_TAG:-}"
case "$LIFT_OBJ_TAG" in
    ""|[A-Za-z0-9]*) ;;
    *) echo "LIFT_OBJ_TAG must be empty or start with [A-Za-z0-9] (got '$LIFT_OBJ_TAG')" >&2; exit 1 ;;
esac
export MCPU

if [ ! -f "$LIFT/ppu_recomp.h" ]; then
    echo "no lift output in $LIFT -- run ppu_lifter.py first" >&2
    exit 1
fi
RUNTIME_LIB="${RUNTIME_LIB:-$PS3/build-macos/libps3recomp_runtime.a}"
if [ ! -f "$RUNTIME_LIB" ]; then
    echo "runtime library missing: cmake --build $PS3/build-macos" >&2
    exit 1
fi

INC=(-I "$LIFT"
     -I "$PS3/include"
     -I "$PS3/runtime/ppu"
     -I "$PS3/runtime/syscalls"
     -I "$PS3/runtime/spu"
     -I "$PS3/runtime/prx"
     -I "$PS3/runtime/memory"
     -I "$PS3/libs/system" -I "$PS3/libs/spurs" -I "$PS3/libs/sync"
     -I "$PS3/libs/video"  -I "$PS3/libs/audio" -I "$PS3/libs/network"
     -I "$PS3/libs/codec")

JOBS="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
JOBS=$(( JOBS > 6 ? 6 : JOBS ))   # each chunk peaks near 1 GB of compiler RSS
OBJ_SUFFIX=".${LIFT_OPT#-O}${LIFT_OBJ_TAG:+.$LIFT_OBJ_TAG}.o"

echo "=== 1. lifted chunks -> .o  LIFT_OPT=$LIFT_OPT (-P $JOBS) ==="
cd "$LIFT"
t0=$(date +%s)
{
    for f in ppu_recomp_*.cpp ppu_stubs.cpp; do
        [ -f "$f" ] || continue
        o="$f$OBJ_SUFFIX"
        if [ "$FORCE_REBUILD_LIFT" = "1" ] || [ ! -f "$o" ] || [ "$f" -nt "$o" ]; then
            echo "$f"
        fi
    done
} | xargs -P "$JOBS" -I {} sh -c \
    'src="$1"; ps3="$2"; opt="$3"; suf="$4"; extra="$5"
     clang++ -std=c++20 "$opt" $MCPU $extra -w -c -I . -I "$ps3/include" -I "$ps3/runtime/ppu" \
         "$src" -o "$src$suf" 2> "$src.cclog"' \
    _ {} "$PS3" "$LIFT_OPT" "$OBJ_SUFFIX" "$LIFT_CFLAGS"
LIFT_OBJS=()
for f in ppu_recomp_*.cpp ppu_stubs.cpp; do
    [ -f "$f" ] || continue
    [ -f "$f$OBJ_SUFFIX" ] && LIFT_OBJS+=("$LIFT/$f$OBJ_SUFFIX")
done
echo "  dur=$(( $(date +%s) - t0 ))s objs=${#LIFT_OBJS[@]} errors=$(cat ./*.cclog 2>/dev/null | grep -c 'error:' || true)"

echo "=== 2. runtime PPU sources -> .o (HOST_OPT=$HOST_OPT) ==="
cd "$HERE"
for src in ppu_loader ppu_imports ppu_hle ppu_sysprx ppu_fs; do
    clang++ -std=c++20 $HOST_OPT $MCPU $HOST_CFLAGS -w -c "${INC[@]}" "$PS3/runtime/ppu/$src.cpp" -o "$LIFT/$src.o"
done
for src in ppu_icall_ascii ppu_vm_fast_policy ppu_p10_ctr; do
    clang -std=c11 $HOST_OPT $MCPU $HOST_CFLAGS -w -c "${INC[@]}" "$PS3/runtime/ppu/$src.c" -o "$LIFT/$src.o"
done

echo "=== 3. HLE NID table -> .o ==="
mkdir -p "$LIFT/gen"
# Same exclusion as the engine CMakeLists (sceNpCommerce.c collides with
# sceNpCommerce2.c and is not in the library).
LIBS=$(ls "$PS3"/libs/*/*.c | xargs -n1 basename | sed 's/\.c$//' | sort -u | grep -vx 'sceNpCommerce')
# shellcheck disable=SC2086
"$PYBIN" "$PS3/tools/gen_hle_nids.py" --out "$LIFT/gen/ppu_hle_nids.cpp" $LIBS > /dev/null
clang++ -std=c++20 $HOST_OPT $MCPU -w -c "${INC[@]}" -I "$PS3/libs" "$LIFT/gen/ppu_hle_nids.cpp" -o "$LIFT/ppu_hle_nids.o"

echo "=== 3b. lifted firmware modules (firmware/, optional) ==="
# dev_flash PRXs lifted by tools/lift_prx.py + ppu_lifter.py (see notes/): lib<m>
# in firmware/lib<m>/ (bind unit) and recomp_prx_<m>/ (lifted code). Only the
# user's own firmware can produce these, so a module that is absent stays HLE.
# vdec/avcdec are NOT in the default list (2026-09-26): the AVC movies decode through the HLE
# cellVdec + VideoToolbox (ps3recomp a867b752); the firmware libavcdec ran as interpreted SPU
# tasks and stalled movies for up to 2 minutes. Firmware path back:
#   LLE_MODULES="sail pamf dmux dmuxpamf adec atxdec vdec avcdec vpost apostsrc" ./build_macos.sh
LLE_MODULES="${LLE_MODULES:-sail pamf dmux dmuxpamf adec atxdec vpost apostsrc}"
LLE_OBJS=()
# Per-module -DPS3_LLE_HAVE_<M> for boot_macos.cpp: an absent module has no
# lib<m>_bind.cpp anywhere in this link, so its g_lle_<m> symbol would be a
# plain undefined weak *declaration* -- on Darwin's static linker that is a
# hard "Undefined symbols" error, not a null pointer (dyld's weak_import
# null-fallback only applies to symbols coming from a separate dylib/
# framework, never to a symbol simply missing from a static executable's own
# link -- confirmed the same way as the PGO writer's weak-declaration note in
# ppu_loader.cpp: declaring is not defining). Gate the declaration and the
# ppu_lle_add() call at compile time instead of relying on the address being
# null at runtime.
LLE_HAVE_DEFS=()
for m in $LLE_MODULES; do
    B="$HERE/firmware/lib$m/lib${m}_bind.cpp"; L="$HERE/recomp_prx_$m"
    if [ ! -f "$B" ] || [ ! -f "$L/ppu_recomp_000.cpp" ]; then
        echo "  lib$m: not present -> HLE"; continue
    fi
    n0=${#LLE_OBJS[@]}
    for f in "$L"/ppu_recomp_*.cpp; do
        o="$f$OBJ_SUFFIX"
        if [ "$FORCE_REBUILD_LIFT" = "1" ] || [ ! -f "$o" ] || [ "$f" -nt "$o" ]; then
            clang++ -std=c++20 "$LIFT_OPT" $MCPU -w -c -I "$L" -I "$PS3/include" \
                -I "$PS3/runtime/ppu" "$f" -o "$o"
        fi
        LLE_OBJS+=("$o")
    done
    clang++ -std=c++20 $HOST_OPT $MCPU -w -c -I "$L" -I "$PS3/include" -I "$PS3/runtime/ppu" \
        "$B" -o "${B%.cpp}.o"
    LLE_OBJS+=("${B%.cpp}.o")
    LLE_HAVE_DEFS+=("-DPS3_LLE_HAVE_$(echo "$m" | tr '[:lower:]' '[:upper:]')=1")
    echo "  lib$m: LLE ($(( ${#LLE_OBJS[@]} - n0 )) objects)"
done

echo "=== 3c. lifted SPU jobs (spu_jobs.toml) ==="
JOB_OBJS=()
JOB_MANIFEST="${JOB_MANIFEST:-$HERE/spu_jobs.toml}"   # override: tests of this step
if [ -f "$JOB_MANIFEST" ]; then
    JOBDIR="$LIFT/spu_jobs"
    # Start from an empty directory: only the jobs named in the manifest are
    # compiled and linked (a job removed from the manifest must not survive in
    # a stale subdirectory, and the count below must be the manifest's).
    rm -rf "$JOBDIR"
    lift_rc=0
    "$PYBIN" "$PS3/tools/lift_spu_jobs.py" --manifest "$JOB_MANIFEST" --elf "$HERE/EBOOT.ELF" \
        --task-dir "$HERE/spu_tasks" --out "$JOBDIR" --prefix ben10 --first-image-id 16 || lift_rc=$?
    if [ "$lift_rc" -eq 2 ]; then
        # Fingerprint mismatch: another game version. The weak
        # ben10_register_spu_jobs covers the link; every job is interpreted.
        echo "WARN: spu_jobs.toml does not match this EBOOT -- lifted jobs off (interpreter)"
        JOB_OBJS=()
    elif [ "$lift_rc" -ne 0 ]; then
        echo "ERROR: lift_spu_jobs.py failed (exit $lift_rc)" >&2
        exit "$lift_rc"
    else
        for c in "$JOBDIR"/*/spu_recomp.c "$JOBDIR"/spu_jobs_register.c; do
            clang -std=c11 -O2 $MCPU $LIFT_CFLAGS -w -c "${INC[@]}" -I "$(dirname "$c")" "$c" -o "$c.o"
            JOB_OBJS+=("$c.o")
        done
        echo "  $(( ${#JOB_OBJS[@]} - 1 )) job(s) lifted"
    fi
fi

echo "=== 4. boot host -> .o ==="
clang++ -std=c++20 $HOST_OPT $MCPU -w -c "${INC[@]}" "${LLE_HAVE_DEFS[@]:-}" \
    "$HERE/boot_macos.cpp" -o "$LIFT/boot_macos.o"

echo "=== 4b. port host units (host/*.c) -> .o ==="
HOST_UNIT_OBJS=()
for c in "$HERE"/host/*.c; do
    [ -f "$c" ] || continue
    case "$(basename "$c")" in test_*) continue ;; esac
    o="$LIFT/host_$(basename "${c%.c}").o"
    clang -std=c11 $HOST_OPT $MCPU $HOST_CFLAGS -Wall -Wextra -c "${INC[@]}" -I "$HERE/host" "$c" -o "$o"
    HOST_UNIT_OBJS+=("$o")
done
echo "  ${#HOST_UNIT_OBJS[@]} host unit(s)"

echo "=== 4c. port host hooks (host/*.cpp, mid-asm hook bodies) -> .o ==="
for c in "$HERE"/host/*.cpp; do
    [ -f "$c" ] || continue
    case "$(basename "$c")" in test_*) continue ;; esac
    o="$LIFT/host_$(basename "${c%.cpp}").o"
    clang++ -std=c++20 $HOST_OPT $MCPU $HOST_CFLAGS -Wall -Wextra -Wno-frame-address -c "${INC[@]}" -I "$HERE/host" "$c" -o "$o"
    HOST_UNIT_OBJS+=("$o")
done
echo "  ${#HOST_UNIT_OBJS[@]} host object(s) in total"

echo "=== 5. link ==="
SDL_FLAGS="${SDL_FLAGS-$(pkg-config --libs sdl2)}"
VK_FLAGS=""
if [ -f /opt/homebrew/lib/libvulkan.dylib ]; then
    VK_FLAGS="-L/opt/homebrew/lib -lvulkan"
    # The runtime archive's Vulkan backend requires shaderc (only compiled in when CMake found it).
    if pkg-config --exists shaderc; then VK_FLAGS="$VK_FLAGS $(pkg-config --libs shaderc)"; fi
fi
if [ -d /opt/homebrew/lib ]; then
    VK_FLAGS="$VK_FLAGS -Wl,-rpath,/opt/homebrew/lib"
fi
clang++ -std=c++20 $HOST_OPT $MCPU $LINK_CFLAGS \
    "${LIFT_OBJS[@]}" \
    "$LIFT"/ppu_loader.o "$LIFT"/ppu_imports.o "$LIFT"/ppu_hle.o \
    "$LIFT"/ppu_sysprx.o "$LIFT"/ppu_fs.o "$LIFT"/ppu_icall_ascii.o \
    "$LIFT"/ppu_vm_fast_policy.o "$LIFT"/ppu_p10_ctr.o \
    "$LIFT"/ppu_hle_nids.o "$LIFT"/boot_macos.o \
    ${LLE_OBJS[@]+"${LLE_OBJS[@]}"} \
    ${JOB_OBJS[@]+"${JOB_OBJS[@]}"} \
    ${HOST_UNIT_OBJS[@]+"${HOST_UNIT_OBJS[@]}"} \
    "$RUNTIME_LIB" \
    -framework Metal -framework MetalFX -framework MetalPerformanceShaders -framework QuartzCore -framework Foundation \
    -framework Cocoa -framework CoreText \
    -framework AVFoundation -framework CoreMedia -framework CoreVideo -framework VideoToolbox \
    -framework AudioToolbox -framework CoreAudio \
    -framework GameController -framework CoreHaptics \
    $SDL_FLAGS $VK_FLAGS -lm -lz \
    -Wl,-stack_size,0x2000000 \
    -o "$OUT"

echo
ls -lh "$OUT"
echo "*** $OUT built (LIFT_OPT=$LIFT_OPT HOST_OPT=$HOST_OPT) ***"
