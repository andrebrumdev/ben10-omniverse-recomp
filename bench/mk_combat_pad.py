#!/usr/bin/env python3
"""Generate bench/s9b_combat.pad: s9b.pad (title -> NEW GAME -> Training Simulation 1, up to
76000 ms) followed by a repeating move/attack/jump cycle from 100000 ms to 100000+SPAN ms
(default 320 s) for soak runs.  Format of PS3_PAD_SCRIPT: "from-to:hexbuttons:lx:ly;..."
(ms on the pad clock; 0x8000 square, 0x4000 cross, 0x2000 circle; stick 128 = centre)."""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
span = int(sys.argv[1]) if len(sys.argv) > 1 else 320000
segs = [s for s in open(os.path.join(here, "s9b.pad")).read().strip().split(";")
        if not s.startswith("100000-")]
cycle = [(0, 700, "0", 255, 128), (700, 800, "8000", 128, 128), (800, 1500, "0", 0, 128),
         (1500, 1600, "8000", 128, 128), (1600, 1700, "4000", 128, 128), (1700, 2400, "0", 200, 40)]
t = 100000
while t < 100000 + span:
    for a, b, btn, x, y in cycle:
        segs.append(f"{t + a}-{t + b}:{btn}:{x}:{y}")
    t += 2400
segs.append(f"{t}-900000:0:128:128")
open(os.path.join(here, "s9b_combat.pad"), "w").write(";".join(segs))
