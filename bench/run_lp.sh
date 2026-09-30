#!/bin/bash
# bench/run_lp.sh -- one measured Ben 10 run (muted, hidden window), serialized by a lock dir.
#
# usage: bench/run_lp.sh <tag> <profile|clean> [ENV=value]...
#   Env overrides are appended after the base recipe, so they win (same as run_ben10.sh).
#   NOTE: this harness does NOT source run_ben10.sh; the base recipe below is the one
#   run_ben10.sh had when the series was taken. Pass RECIPE_ENV ("A=1 B=2") to append recipe
#   variables that run_ben10.sh gained later (e.g. RECIPE_ENV="PS3_GIANT_HANDOFF=1").
#
# Parameters (environment):
#   BENCH_OUT   output dir: lp_<tag>.log / .meta / .thr / .sample*.txt   (default: bench/out)
#   BIN         binary name in the port dir                           (default: boot_ben10)
#   LOCK_DIR    mkdir-atomic lock, shared by every session that runs a game
#               (default: $BENCH_OUT/gamelock)
#   PS3RECOMP   ps3recomp checkout, only to record its rev          (default: ../ps3recomp)
#   PAD_FILE    PS3_PAD_SCRIPT text file                             (default: bench/s9b.pad)
#   STOP_AFTER  seconds to keep running after the LEVEL loading screen (default 35; soak: 240+)
#   CAP         hard cap in seconds since start                       (default 175; soak: 420)
#   EXTRA_TRACE extra PS3_TRACE_* vars ("PS3_X=1 PS3_Y=1") added to the base trace set
#
# Stops STOP_AFTER s after the LEVEL loading screen (first .ls open at t>55 s), cap CAP s.
# Refuses to run on battery; waits while any game process (boot_ben10*, boot_gow2*, g2play)
# is running -- the USER may be playing -- and only ever kills its own pid.
HERE="$(cd "$(dirname "$0")" && pwd)"
B="$(cd "$HERE/.." && pwd)"
BENCH_OUT="${BENCH_OUT:-$HERE/out}"; mkdir -p "$BENCH_OUT"
BIN="${BIN:-boot_ben10}"
LOCK_DIR="${LOCK_DIR:-$BENCH_OUT/gamelock}"
PS3RECOMP="${PS3RECOMP:-$B/../ps3recomp}"
PAD_FILE="${PAD_FILE:-$HERE/s9b.pad}"
STOP_AFTER="${STOP_AFTER:-35}"; CAP="${CAP:-175}"
TAG=${1:?tag}; MODE=${2:?profile|clean}; shift 2
P="$BENCH_OUT"
GAMERE="^(\./|/[^ ]*/)?(boot_ben10[A-Za-z0-9_]*|boot_gow2[A-Za-z0-9_]*|g2play) "

until mkdir "$LOCK_DIR" 2>/dev/null; do sleep 5; done
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT
while pgrep -f "$GAMERE" >/dev/null; do sleep 5; done
if pmset -g batt | grep -q "Battery Power"; then echo "on battery, abort" > "$P/lp_$TAG.meta"; exit 1; fi
[ -x "$P/thrmon" ] || clang -O2 -o "$P/thrmon" "$HERE/thrmon.c" || exit 1
PAD_SCRIPT="$(cat "$PAD_FILE")"
cd "$P"
( env PS3_VFS_ROOT="$B/extracted/PS3_GAME/USRDIR" \
    PS3_RSX_FIFO=1 PS3_GCM_CB=1 PS3_LWMUTEX_REAL=1 PS3_GCM_REF_BUMP=0 \
    PS3_SPU_TASK_INTERP=1 PS3_METAL_PER_DRAW_RT=1 PS3_VDEC_ASYNC=1 \
    PS3_MUTE=1 PS3_WINDOW_HIDDEN=1 PS3_TRACE_AUDIO=1 PS3_TRACE_FPS=1 PS3_TRACE_GIANTSTAT=1 PS3_TRACE_FRAMETIME=1 \
    PS3_PAD_AUTOSTART=1 PS3_PAD_SCRIPT="$PAD_SCRIPT" $EXTRA_TRACE $RECIPE_ENV \
    "$@" "$B/$BIN" "$B/EBOOT.ELF" 2>&1 | perl -MTime::HiRes=time -ne 'BEGIN{$|=1;$t0=time; printf("T0 %.3f\n",$t0)} printf("%8.2f %s",time-$t0,$_)' > "$P/lp_$TAG.log" ) &
sleep 3; PID=$(pgrep -n -f "^$B/$BIN $B/EBOOT.ELF")
RTLIB="$PS3RECOMP/build-macos/libps3recomp_runtime.a"
echo "pid=$PID mode=$MODE env: $RECIPE_ENV $EXTRA_TRACE $* bin=$BIN bin_mtime=$(stat -f %Sm -t '%d/%m %H:%M:%S' "$B/$BIN") runtime_lib_mtime=$(stat -f %Sm -t '%d/%m %H:%M:%S' "$RTLIB" 2>/dev/null) ps3recomp=$(git -C "$PS3RECOMP" rev-parse --short HEAD 2>/dev/null) port=$(git -C "$B" rev-parse --short HEAD) stop_after=$STOP_AFTER cap=$CAP start=$(date +%H:%M:%S) batt=$(pmset -g batt | head -1 | tr -d "'")" > "$P/lp_$TAG.meta"
[ -n "$PID" ] || { echo "no pid (binary did not start)" >> "$P/lp_$TAG.meta"; exit 1; }
"$P/thrmon" "$PID" 1000 | perl -MTime::HiRes=time -ne 'printf("%.3f %s",time,$_)' > "$P/lp_$TAG.thr" &
T0=$(date +%s); LVL=0; SAMPLED=0; SG=0; WARM=0
while kill -0 "$PID" 2>/dev/null; do
  NOW=$(( $(date +%s) - T0 ))
  if [ $LVL = 0 ] && awk '$1>55 && /LoadingScreens\/.*\.ls'"'"'/ {f=1} END{exit !f}' "$P/lp_$TAG.log" 2>/dev/null; then
    LVL=$NOW
    # machine regime at the level .ls: loadavg + top 3 NON-game processes (other sessions compiling steal CPU)
    echo "level_ls_seen_at_harness_s=$NOW load=$(sysctl -n vm.loadavg) top: $(ps -Ao %cpu=,comm= -r | grep -v boot_ben10 | head -3 | awk '{n=split($2,a,"/"); printf "%s:%s ",$1,a[n]}')" >> "$P/lp_$TAG.meta"
  fi
  if [ $MODE = profile ] && [ $NOW -ge 25 ] && [ $WARM = 0 ]; then WARM=1
     sample "$PID" 1 -mayDie -file "$P/lp_$TAG.sampleW.txt" >/dev/null 2>&1; fi
  if [ $MODE = profile ] && [ $LVL != 0 ] && [ $SAMPLED = 0 ]; then SAMPLED=1
     kill -USR1 "$PID"; sample "$PID" 3 -mayDie -file "$P/lp_$TAG.sampleL.txt" >/dev/null 2>&1; fi
  if [ $MODE = profile ] && [ $LVL != 0 ] && [ $SG = 0 ] && [ $NOW -ge $((LVL+25)) ]; then SG=1
     sample "$PID" 4 -mayDie -file "$P/lp_$TAG.sampleG.txt" >/dev/null 2>&1; fi
  if [ $LVL != 0 ] && [ $NOW -ge $((LVL+STOP_AFTER)) ]; then break; fi
  [ $NOW -ge "$CAP" ] && break
  sleep 0.3
done
kill -0 "$PID" 2>/dev/null && echo "alive_at_stop=1" >> "$P/lp_$TAG.meta" || echo "alive_at_stop=0 (process exited on its own)" >> "$P/lp_$TAG.meta"
kill -9 "$PID" 2>/dev/null; sleep 1; echo "done after $(( $(date +%s) - T0 ))s" >> "$P/lp_$TAG.meta"
