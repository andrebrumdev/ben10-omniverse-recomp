#!/usr/bin/env bash
# Run the Ben 10 Omniverse host. Env recipe measured 2026-09-24 (see notes/):
#   PS3_RSX_FIFO=1       walk the RSX FIFO (SET_REFERENCE/semaphores/labels)
#   PS3_GCM_CB=1         CellGcmContextData overflow callback
#   PS3_LWMUTEX_REAL=1   real lwmutex exclusion
#   PS3_GCM_REF_BUMP=0   no legacy ref++ (the frame loop waits on exact ref values)
#   PS3_SPU_TASK_INTERP=1  SPURS tasks with no lifted image run in the SPU
#                          interpreter (the game's own task + firmware codec tasks)
# PS3_NO_RSX=1 for headless. Extra args are passed through as env overrides:
#   ./run_ben10.sh PS3_TRACE_JOBCHAIN=1
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
exec env PS3_VFS_ROOT="$HERE/extracted/PS3_GAME/USRDIR" \
    PS3_RSX_FIFO=1 PS3_GCM_CB=1 PS3_LWMUTEX_REAL=1 PS3_GCM_REF_BUMP=0 \
    PS3_SPU_TASK_INTERP=1 \
    "$@" ./boot_ben10 EBOOT.ELF
