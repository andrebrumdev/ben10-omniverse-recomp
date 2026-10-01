#!/usr/bin/env bash
# Test of the run_ben10.sh env recipe: a stub "binary" prints its environment.
# Run: bash bench/test_run_ben10_env.sh
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="$(cd "$HERE/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
printf '#!/bin/sh\nenv\n' > "$T/stub"; chmod +x "$T/stub"
fail=0
run() { BOOT_BIN="$T/stub" "$PORT/run_ben10.sh" "$@"; }
check() {   # check <description> <grep -x pattern> [run args...]
    local d="$1" pat="$2"; shift 2
    if run "$@" | grep -qx -- "$pat"; then echo "ok   $d"; else echo "FAIL $d"; fail=1; fi
}
check "default recipe sets PS3_GIANT_HANDOFF=1" "PS3_GIANT_HANDOFF=1"
check "override PS3_GIANT_HANDOFF=0 passes through (A/B)" "PS3_GIANT_HANDOFF=0" PS3_GIANT_HANDOFF=0
# the override must REPLACE the default, not add a second value
n=$(run PS3_GIANT_HANDOFF=0 | grep -c '^PS3_GIANT_HANDOFF=')
if [ "$n" = 1 ]; then echo "ok   override leaves exactly one PS3_GIANT_HANDOFF"; else echo "FAIL override leaves $n PS3_GIANT_HANDOFF lines"; fail=1; fi
check "default recipe sets PS3_VM_FAST_MASK=0x7F" "PS3_VM_FAST_MASK=0x7F"
check "override PS3_VM_FAST_MASK=0 passes through (A/B)" "PS3_VM_FAST_MASK=0" PS3_VM_FAST_MASK=0
n=$(run PS3_VM_FAST_MASK=0 | grep -c '^PS3_VM_FAST_MASK=')
if [ "$n" = 1 ]; then echo "ok   override leaves exactly one PS3_VM_FAST_MASK"; else echo "FAIL override leaves $n PS3_VM_FAST_MASK lines"; fail=1; fi
check "HANDOFF kept alongside the mask" "PS3_GIANT_HANDOFF=1"
check "base recipe kept (PS3_RSX_FIFO=1)" "PS3_RSX_FIFO=1"
exit $fail
