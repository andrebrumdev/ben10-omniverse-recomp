#!/usr/bin/env python3
"""Diagnostic probe (gated OFF): log the per-frame tick argument of the Ben 10 frame advance.

func_000B5C4C (BLUS31017 EBOOT) is called once per frame with r3 = int(frame_time_seconds * 600.0f),
the game's logic step in 1/600 s ticks (20 at 29.97 fps, 10 at 59.94 fps). This script copies a lift dir
into a scratch dir (symlinks, objects reused) and inserts a probe at the entry of func_000B5C4C that, with
PS3_EXP_TICKLOG=1, prints once per host second:
  [TICKLOG] calls=N ticks_sum=S game_s=S/600 wall_s=W ratio=game/wall
Idempotent; never touches the original lift.

  python3 tools/probe_ticklog.py recomp_macos recomp_macos_lim
  OUT=./boot_ben10_tick ./build_macos.sh recomp_macos_lim
"""
import os, re, sys

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
MARK = "PS3_EXP_TICKLOG"
for name in os.listdir(src):
    s, d = os.path.join(src, name), os.path.join(dst, name)
    if name == "ppu_recomp_000.cpp" or name.startswith("ppu_recomp_000.cpp."):
        continue
    # only the lifted code and the SPU jobs are shared; runtime objects (ppu_loader.o ...) and gen/ are rebuilt
    # in the scratch dir so the build never writes through a symlink into the original lift
    if not (name.startswith("ppu_recomp") or name.startswith("ppu_stubs") or name == "spu_jobs"):
        continue
    if os.path.lexists(d):
        continue
    os.symlink(os.path.abspath(s), d)
code = open(os.path.join(src, "ppu_recomp_000.cpp"), errors="ignore").read()
if MARK in code:
    sys.exit("source lift already has the probe")
entry = "void func_000B5C4C(ppu_context* ctx) {\n"
assert code.count(entry) == 1
probe = entry + r'''        { static int s_on = -1; static uint64_t s_calls, s_sum, s_t0; static uint32_t s_hist[64];
          if (s_on < 0) s_on = getenv("PS3_EXP_TICKLOG") ? 1 : 0;
          if (s_on) {
              struct timespec ts_; clock_gettime(CLOCK_MONOTONIC, &ts_);
              uint64_t now_ = (uint64_t)ts_.tv_sec * 1000000000ull + (uint64_t)ts_.tv_nsec;
              uint32_t a_ = (uint32_t)ctx->gpr[3];
              s_calls++; s_sum += a_; if (a_ < 64) s_hist[a_]++;
              if (!s_t0) s_t0 = now_;
              if (now_ - s_t0 >= 1000000000ull) {
                  double wall_ = (double)(now_ - s_t0) / 1e9;
                  fprintf(stderr, "[TICKLOG] calls=%llu ticks_sum=%llu game_s=%.4f wall_s=%.4f ratio=%.4f hist:",
                          (unsigned long long)s_calls, (unsigned long long)s_sum, (double)s_sum / 600.0, wall_,
                          ((double)s_sum / 600.0) / wall_);
                  for (int i_ = 0; i_ < 64; i_++) if (s_hist[i_]) { fprintf(stderr, " %d:%u", i_, s_hist[i_]); s_hist[i_] = 0; }
                  fprintf(stderr, "\n");
                  s_calls = s_sum = 0; s_t0 = now_;
              }
          } }
'''
code = code.replace(entry, probe, 1)
# the frame-rate mode setter (switch on r3: 1 -> 10 ticks / 1/59.94 s, 2 -> 30 ticks / 1/19.98 s, else 20 ticks / 1/29.97 s)
for fn in ("func_00058358", "func_000583D8", "func_000B2638"):
    entry2 = "void %s(ppu_context* ctx) {\n" % fn
    assert code.count(entry2) == 1, fn
    probe2 = entry2 + (r'''        { static int s_on2 = -1; if (s_on2 < 0) s_on2 = getenv("PS3_EXP_TICKLOG") ? 1 : 0;
          if (s_on2) fprintf(stderr, "[FRMODE] %s(r3=%%d r4=%%d) lr=0x%%llX tid=%%llu\n", (int)(int32_t)ctx->gpr[3], (int)(int32_t)ctx->gpr[4],
                             (unsigned long long)ctx->lr, (unsigned long long)ctx->thread_id); }
''' % fn)
    code = code.replace(entry2, probe2, 1)
if "#include <time.h>" not in code[:20000]:
    code = "#include <time.h>\n#include <stdio.h>\n#include <stdlib.h>\n" + code
open(os.path.join(dst, "ppu_recomp_000.cpp"), "w").write(code)
print("ok", dst)
