#!/usr/bin/env python3
"""Generate bench/s9b_reload.pad: s9b.pad (title -> NEW GAME -> Training Simulation 1, up to
76000 ms) + CROSS taps every 2 s from 100 s (dismiss tutorial popups, advance dialogue, jump in
combat) + RELOAD cycles that go pause -> Select Level -> Training Time -> confirm YES, i.e. a
second/third level load without leaving the process.

Menu map (read from frame dumps 2026-09-30, PS3_METAL_SHOW_DUMP_EVERY):
  START            pause menu: Omnitrix / Character Upgrade / Collectibles / Options /
                   Select Level / Load Game / Quit (cursor starts on Omnitrix)
  DPAD DOWN x4     -> Select Level; CROSS opens the list (one entry: "Training Time")
  CROSS            confirm -> "ARE YOU SURE YOU WANT TO LOAD?" (cursor on NO: a CROSS here
                   just returns to the list)
  DPAD LEFT, CROSS -> YES -> the level reloads (a new .ls open, then draws>=100)
CROSS = select/confirm/OK, CIRCLE = back.  The pad clock is wall time (pad_autostart_elapsed_ms),
not game events, so the cycle starts are spread out to survive a slower machine
(the level .ls opens between 70 and 105 s depending on the regime).

usage: mk_reload_pad.py [cycle_start_s ...]   (default 190 340 490)"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
starts = [int(a) * 1000 for a in sys.argv[1:]] or [190000, 340000, 490000]
END = 900000
segs = [s for s in open(os.path.join(here, "s9b.pad")).read().strip().split(";")
        if not s.startswith("100000-")]
ev = []      # (from_ms, to_ms, buttons_hex, lx, ly)
def press(t, btn, hold=150): ev.append((t, t + hold, btn, 128, 128))
for cs in starts:
    press(cs, "8", 200)                              # START
    for i in range(4): press(cs + 5000 + 700 * i, "40")   # DPAD DOWN x4
    press(cs + 9000, "4000")                         # CROSS: open Select Level
    press(cs + 14000, "4000")                        # CROSS: pick Training Time
    press(cs + 19000, "80")                          # DPAD LEFT: YES
    press(cs + 21000, "4000")                        # CROSS: confirm
quiet = [(cs - 8000, cs + 30000) for cs in starts]
t = 100000
while t < END:
    if not any(a <= t < b for a, b in quiet): press(t, "4000")
    t += 2000
ev.sort()
for a, b, btn, x, y in ev:
    segs.append(f"{a}-{b}:{btn}:{x}:{y}")
segs.append(f"{END}-{END + 900000}:0:128:128")   # tail; gaps in between mean "no input"
open(os.path.join(here, "s9b_reload.pad"), "w").write(";".join(segs))
