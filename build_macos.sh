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
OBJ_SUFFIX=".${LIFT_OPT#-O}.o"

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
    'src="$1"; ps3="$2"; opt="$3"; suf="$4"
     clang++ -std=c++20 "$opt" $MCPU -w -c -I . -I "$ps3/include" -I "$ps3/runtime/ppu" \
         "$src" -o "$src$suf" 2> "$src.cclog"' \
    _ {} "$PS3" "$LIFT_OPT" "$OBJ_SUFFIX"
LIFT_OBJS=()
for f in ppu_recomp_*.cpp ppu_stubs.cpp; do
    [ -f "$f" ] || continue
    [ -f "$f$OBJ_SUFFIX" ] && LIFT_OBJS+=("$LIFT/$f$OBJ_SUFFIX")
done
echo "  dur=$(( $(date +%s) - t0 ))s objs=${#LIFT_OBJS[@]} errors=$(cat ./*.cclog 2>/dev/null | grep -c 'error:' || true)"

echo "=== 2. runtime PPU sources -> .o (HOST_OPT=$HOST_OPT) ==="
cd "$HERE"
for src in ppu_loader ppu_imports ppu_hle ppu_sysprx ppu_fs; do
    clang++ -std=c++20 $HOST_OPT $MCPU -w -c "${INC[@]}" "$PS3/runtime/ppu/$src.cpp" -o "$LIFT/$src.o"
done
for src in ppu_icall_ascii ppu_vm_fast_policy ppu_p10_ctr; do
    clang -std=c11 $HOST_OPT $MCPU -w -c "${INC[@]}" "$PS3/runtime/ppu/$src.c" -o "$LIFT/$src.o"
done

echo "=== 3. HLE NID table -> .o ==="
mkdir -p "$LIFT/gen"
# Same exclusion as the engine CMakeLists (sceNpCommerce.c collides with
# sceNpCommerce2.c and is not in the library).
LIBS=$(ls "$PS3"/libs/*/*.c | xargs -n1 basename | sed 's/\.c$//' | sort -u | grep -vx 'sceNpCommerce')
# shellcheck disable=SC2086
"$PYBIN" "$PS3/tools/gen_hle_nids.py" --out "$LIFT/gen/ppu_hle_nids.cpp" $LIBS > /dev/null
clang++ -std=c++20 $HOST_OPT $MCPU -w -c "${INC[@]}" -I "$PS3/libs" "$LIFT/gen/ppu_hle_nids.cpp" -o "$LIFT/ppu_hle_nids.o"

echo "=== 4. boot host -> .o ==="
clang++ -std=c++20 $HOST_OPT $MCPU -w -c "${INC[@]}" "$HERE/boot_macos.cpp" -o "$LIFT/boot_macos.o"

echo "=== 5. link ==="
SDL_FLAGS="${SDL_FLAGS-$(pkg-config --libs sdl2)}"
VK_FLAGS=""
if [ -f /opt/homebrew/lib/libvulkan.dylib ]; then
    VK_FLAGS="-L/opt/homebrew/lib -lvulkan"
fi
clang++ -std=c++20 $HOST_OPT $MCPU \
    "${LIFT_OBJS[@]}" \
    "$LIFT"/ppu_loader.o "$LIFT"/ppu_imports.o "$LIFT"/ppu_hle.o \
    "$LIFT"/ppu_sysprx.o "$LIFT"/ppu_fs.o "$LIFT"/ppu_icall_ascii.o \
    "$LIFT"/ppu_vm_fast_policy.o "$LIFT"/ppu_p10_ctr.o \
    "$LIFT"/ppu_hle_nids.o "$LIFT"/boot_macos.o \
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
