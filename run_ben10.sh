#!/usr/bin/env bash
# Run the Ben 10 Omniverse host. Env recipe measured 2026-09-24 (see notes/):
#   PS3_RSX_FIFO=1       walk the RSX FIFO (SET_REFERENCE/semaphores/labels)
#   PS3_GCM_CB=1         CellGcmContextData overflow callback
#   PS3_LWMUTEX_REAL=1   real lwmutex exclusion
#   PS3_GCM_REF_BUMP=0   no legacy ref++ (the frame loop waits on exact ref values)
#   (each draw into the surface it targets, and cellVdec decoding on its own
#    thread for the VideoToolbox H.264 path, are engine defaults on macOS now)
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
#   PS3_JC_WORKERS=2    the job chain runs the jobs between two barriers on 2 host "SPUs" (jm2 semantics,
#                        libs/spurs/cellSpursJobChain.c; workers = min(N, chain maxContention 6, SPURS nSpus 5)).
#                        Before: one walker thread ran every job serially (98% busy = the gameplay critical
#                        path, 229 jobs/frame). Gameplay (Training Simulation 1, t>=130 s, 84-140 s windows,
#                        interleaved, same binary): frametime p50 61 -> 46 ms pooled over 5 runs of
#                        PS3_JC_WORKERS=2 (-25%), -18% in the two quiet-machine runs (48 -> 40 ms), fps median
#                        16 -> 21; PS3_JC_DIFF=1 with 2 and with 3 workers: 0 divergences in ~180k jobs per
#                        run; a 271 s run did not hang. 3 workers reach the title's ~30 fps (median 29, p50 34 ms)
#                        for one more busy core: ./run_ben10.sh PS3_JC_WORKERS=3. Serial walker (old behaviour):
#                        ./run_ben10.sh PS3_JC_WORKERS=1. Evidence: docs/superpowers/plans/2026-09-30-ben10-pipeline-opportunities.md
#                        (ps3recomp, Tasks 3-4) and bench/README.md.
#                        COST (measured in the same T4 logs, revisao adversarial): audio blocks skipped in
#                        gameplay (t>=130 s) grow with the worker count, because the job workers compete
#                        with the audio producer for cores. Quiet machine: 1 worker 0.06% (19-20 blocks in
#                        ~182 s, 3 runs, old binary included), 2 workers 0.7-1.0% (RVSOAK 592 s: 0.72%;
#                        h2 271 s: 1.04%), 3 workers 4.9-7.9% (loaded regime, no quiet 3-worker run).
#                        Loading screens stay at 0% (HANDOFF). If the crackle bothers more than the ~+30% fps
#                        gain: ./run_ben10.sh PS3_JC_WORKERS=1.
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
    PS3_SPU_TASK_INTERP=1 PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F PS3_JC_WORKERS=2 \
    "$@" "${BOOT_BIN:-./boot_ben10}" EBOOT.ELF
