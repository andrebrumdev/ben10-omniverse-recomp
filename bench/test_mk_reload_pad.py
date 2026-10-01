#!/usr/bin/env python3
"""Offline test of mk_reload_pad.py: the generated PS3_PAD_SCRIPT is well-formed (same grammar as
libs/input/pad_autostart.c pad_script_at_ms), has no overlapping segments, and each reload cycle
is START, 4x DOWN, CROSS, CROSS, LEFT, CROSS with no stray CROSS tap in its quiet window.
Run: python3 bench/test_mk_reload_pad.py"""
import os, re, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
subprocess.check_call([sys.executable, os.path.join(here, "mk_reload_pad.py"), "190", "340"])
text = open(os.path.join(here, "s9b_reload.pad")).read()
rx = re.compile(r"^(\d+)-(\d+):([0-9a-fA-F]+):(\d+):(\d+)$")
segs = []
for s in text.split(";"):
    m = rx.match(s)
    assert m, "malformed segment (the C parser would stop here): %r" % s
    a, b, btn, x, y = int(m[1]), int(m[2]), int(m[3], 16), int(m[4]), int(m[5])
    assert a < b and btn <= 0xFFFF and x <= 255 and y <= 255, s
    segs.append((a, b, btn))
ordered = sorted(segs)
for p, q in zip(ordered, ordered[1:]):
    assert p[1] <= q[0], "overlap %r %r" % (p, q)
def at(lo, hi): return [s for s in segs if lo <= s[0] < hi]
for cs in (190000, 340000):
    got = [s[2] for s in sorted(at(cs, cs + 30000)) if s[2]]
    want = [0x8, 0x40, 0x40, 0x40, 0x40, 0x4000, 0x4000, 0x80, 0x4000]
    assert got == want, "cycle at %d: %r != %r" % (cs, got, want)
    assert not [s for s in at(cs - 8000, cs) if s[2] == 0x4000], "stray CROSS before the cycle"
assert any(s[2] == 0x4000 for s in at(100000, 180000)), "no CROSS taps before the first cycle"
print("ok mk_reload_pad: %d segments, 2 cycles" % len(segs))
