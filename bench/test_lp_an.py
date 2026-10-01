#!/usr/bin/env python3
"""Test of bench/lp_an.py (windows by event) on a synthetic log.  Run: python3 bench/test_lp_an.py"""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_an  # noqa: E402  (fails until the module exists)


def synth(last_s=99, with_level_ls=True):
    """One [FPS]/[AUDIO]/[GIANTSTAT] line per second from t=60 to last_s.
    Level .ls opens at t=70.10; draws=3 on the loading seconds 70..73, 150 otherwise;
    2 audio seconds (71, 72) skip 8 blocks; giant max_wait per load second = 10/20/30/40/5."""
    lines = ["T0 1000.000"]
    if with_level_ls:
        lines.append("   70.10 [fs] open '/dev_bdvd/PS3_GAME/USRDIR/LoadingScreens/x.ls' -> fd 3 (lr=0x2EC00)")
    maxw = {70: 10.0, 71: 20.0, 72: 30.0, 73: 40.0, 74: 5.0}
    for s in range(60, last_s + 1):
        draws = 3 if 70 <= s <= 73 else 150
        skip = 8 if s in (71, 72) else 0
        t = s + 0.43
        lines.append(f"{t:8.2f} [FPS] fps=29 draws={draws} present_ms_avg=0.07 present_ms_max=0.10 gpu_ms=0.44 "
                     f"decode_ms_avg=0.03 giant_wait_ms=10.0 giant_hold_ms=20.0 giant_acq=1000")
        lines.append(f"{t:8.2f} [AUDIO] t=1.0 blocos=188 pico=0.0000 cru=0.0000 espera=0 pulados={skip} "
                     f"perdidos=0 falta=0 anel=1280 portos=1/1 mudo=1")
        lines.append(f"{t:8.2f} [GIANTSTAT] mode=normal thr_us=1000 max_wait_ms={maxw.get(s, 1.0)} slow_acq=1 "
                     f"max_hold_ms=2.0 starve_entries=0 handoffs=0 starving=0")
    return "\n".join(lines) + "\n"


class T(unittest.TestCase):
    def run_log(self, text):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "lp_t.log"), "w") as f:
                f.write(text)
            return lp_an.an(d, "t")

    def test_window_skip_and_maxwait(self):
        r = self.run_log(synth())
        self.assertTrue(r["valid"])
        self.assertAlmostEqual(r["level_ls"], 70.10, places=2)
        self.assertAlmostEqual(r["load_s"], 74 - 70.10, places=2)   # first draws>=100 second after the .ls
        self.assertEqual(r["load_skip"], 16)
        self.assertAlmostEqual(r["load_skip_pct"], 100 * 16 / (188 * 5), places=3)   # window = seconds 70..74
        self.assertEqual(r["load_gmaxwait_med"], 20.0)   # median of 10,20,30,40,5
        self.assertEqual(r["load_gmaxwait"], 40.0)

    def test_hub_open_is_not_the_level_and_has_own_skip_window(self):
        """A hub .ls at t=30 (10<t<=55) must not be taken as the level load (t>55) and has a 5 s skip window."""
        text = synth()
        extra = ["   30.10 [fs] open '/dev_bdvd/PS3_GAME/USRDIR/LoadingScreens/hub.ls' -> fd 3 (lr=0x2EC00)"]
        for s in range(30, 36):
            skip = 94 if s in (31, 34) else 0        # 188 blocks skipped in the 5 s window 30..34
            extra.append(f"{s + 0.43:8.2f} [AUDIO] t=1.0 blocos=188 pico=0.0000 cru=0.0000 espera=0 pulados={skip} "
                         f"perdidos=0 falta=0 anel=1280 portos=1/1 mudo=1")
        r = self.run_log(text.replace("T0 1000.000\n", "T0 1000.000\n" + "\n".join(extra) + "\n", 1))
        self.assertAlmostEqual(r["level_ls"], 70.10, places=2)
        self.assertAlmostEqual(r["hub_skip_pct"], 100 * 188 / (188 * 5), places=3)   # 20 %
        self.assertEqual(r["load_skip"], 16)         # the hub skips are outside the level window

    def test_invalid_when_short_after_level(self):
        r = self.run_log(synth(last_s=85))          # only 12 s of draws>=100 after the load
        self.assertFalse(r["valid"])

    def test_invalid_without_level_ls(self):
        r = self.run_log(synth(with_level_ls=False))
        self.assertFalse(r["valid"])
        self.assertNotIn("load_s", r)


if __name__ == "__main__":
    unittest.main()
