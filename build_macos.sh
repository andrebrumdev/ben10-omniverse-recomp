#!/usr/bin/env bash
# Build the Ben 10 Omniverse native macOS/arm64 host.
#
# Generic subset of games/gow2/build_macos.sh: lifted chunks + runtime PPU
# sources + generated HLE NID table + boot host + link against
# libps3recomp_runtime.a. No game-specific host code, hooks or SPU images yet.
#
# Assumes the lift already ran:
#   python3 ../ps3recomp/tools/ppu_lifter.py EBOOT.ELF --functions functions.json -o recomp_macos -j 8
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
LLE_MODULES="${LLE_MODULES:-sail pamf dmux dmuxpamf adec atxdec vdec avcdec vpost apostsrc}"
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
if [ -f "$HERE/spu_jobs.toml" ]; then
    JOBDIR="$LIFT/spu_jobs"
    "$PYBIN" "$PS3/tools/lift_spu_jobs.py" --manifest "$HERE/spu_jobs.toml" --elf "$HERE/EBOOT.ELF" \
        --out "$JOBDIR" --prefix ben10 --first-image-id 16
    for c in "$JOBDIR"/*/spu_recomp.c "$JOBDIR"/spu_jobs_register.c; do
        clang -std=c11 -O2 $MCPU $LIFT_CFLAGS -w -c "${INC[@]}" -I "$(dirname "$c")" "$c" -o "$c.o"
        JOB_OBJS+=("$c.o")
    done
    echo "  $(( ${#JOB_OBJS[@]} - 1 )) job(s) lifted"
fi

echo "=== 4. boot host -> .o ==="
clang++ -std=c++20 $HOST_OPT $MCPU -w -c "${INC[@]}" "${LLE_HAVE_DEFS[@]:-}" \
    "$HERE/boot_macos.cpp" -o "$LIFT/boot_macos.o"

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
    "$RUNTIME_LIB" \
    -framework Metal -framework MetalFX -framework MetalPerformanceShaders -framework QuartzCore -framework Foundation \
    -framework Cocoa -framework CoreText \
    -framework AVFoundation -framework CoreMedia -framework CoreVideo -framework VideoToolbox \
    -framework AudioToolbox -framework CoreAudio \
    -framework GameController -framework CoreHaptics \
    $SDL_FLAGS $VK_FLAGS -lm \
    -Wl,-stack_size,0x2000000 \
    -o "$OUT"

echo
ls -lh "$OUT"
echo "*** $OUT built (LIFT_OPT=$LIFT_OPT HOST_OPT=$HOST_OPT) ***"
