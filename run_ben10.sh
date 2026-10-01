#!/usr/bin/env bash
# Run the Ben 10 Omniverse host. Env recipe measured 2026-09-24 (see notes/):
#   PS3_RSX_FIFO=1       walk the RSX FIFO (SET_REFERENCE/semaphores/labels)
#   PS3_GCM_CB=1         CellGcmContextData overflow callback
#   PS3_LWMUTEX_REAL=1   real lwmutex exclusion
#   PS3_GCM_REF_BUMP=0   no legacy ref++ (the frame loop waits on exact ref values)
#   PS3_METAL_PER_DRAW_RT=1  each draw into the surface it targets (as env_gow2.sh; the
#                        single-pass default showed a black window for Ben 10)
#   PS3_VDEC_ASYNC=1     cellVdec HLE decodes on its own thread (VideoToolbox H.264 path)
#   PS3_SPU_TASK_INTERP=1  SPURS tasks with no lifted image run in the SPU
#                          interpreter (the game's own task + firmware codec tasks)
#   PS3_GIANT_HANDOFF=1  real handoff of the giant lock (E415, runtime/ppu/ppu_loader.cpp:84-135):
#                        the out-of-line vm_read* poll the timeslice flag and a preempt waits until
#                        another thread actually took the lock, so the audio producer
#                        (ppu:veMultiStream, prio 0) no longer sits behind the loader for 15-57 ms
#                        (skips on loading screens 14% -> 0%; approximates lv2's 2 HW threads + priority
#                        run queue). Measured in docs/superpowers/plans/2026-09-30-ben10-pipeline-opportunities.md
#                        (ps3recomp). A/B override: ./run_ben10.sh PS3_GIANT_HANDOFF=0
#   PS3_VM_FAST_MASK=0x7F  every vm_read*/vm_write* accessor takes the fast path from boot
#                        (runtime/ppu/ppu_loader.cpp:1636; it keeps the giant-lock preempt, OOB and
#                        reservation steps and skips the gated probes). Level load 8.3 s -> 5.6 s
#                        (median of 3 interleaved pairs, -33 %), loader thread CPU -45..-53 %, skips stay 0.
#                        Soaked 631 s with 3 reloads of the level through the pause menu (pause -> Select
#                        Level -> YES; bench/mk_reload_pad.py): no stall. GoW2 saw the same mask stall its
#                        level load (cause unknown) -- not reproduced on this title (measured above);
#                        a stall here: ./run_ben10.sh PS3_VM_FAST_MASK=0 (A/B override).
#                        Evidence: docs/superpowers/plans/2026-09-30-ben10-pipeline-opportunities.md (ps3recomp).
#   PS3_DEV_FLASH=<dir>  host firmware tree for /dev_flash (read-only). Unset:
#                        the RPCS3 install's dev_flash when present
#                        ($HOME/Library/Application Support/rpcs3/dev_flash on
#                        macOS); "" disables. libatxdec opens
#                        /dev_flash/sys/external/flashATRAC.pic from it.
# PS3_NO_RSX=1 for headless. Extra args are passed through as env overrides:
#   ./run_ben10.sh PS3_TRACE_JOBCHAIN=1
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
# export PS3_DEV_FLASH="$HOME/Library/Application Support/rpcs3/dev_flash"   # = default when unset
exec env PS3_VFS_ROOT="$HERE/extracted/PS3_GAME/USRDIR" \
    PS3_RSX_FIFO=1 PS3_GCM_CB=1 PS3_LWMUTEX_REAL=1 PS3_GCM_REF_BUMP=0 \
    PS3_SPU_TASK_INTERP=1 PS3_METAL_PER_DRAW_RT=1 PS3_VDEC_ASYNC=1 PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F \
    "$@" "${BOOT_BIN:-./boot_ben10}" EBOOT.ELF
