#!/usr/bin/env python3
"""Test of bench/fs_an.py (speed + landmark check of the frame-step A/B) on synthetic logs.
Run: python3 bench/test_fs_an.py"""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fs_an

LS = "[fs] open '/dev_bdvd/PS3_GAME/USRDIR/LoadingScreens/%016X.ls' -> fd 3 (lr=0x2EC00)"


def fps_line(t, fps, draws=150):
    return "%8.2f [FPS] fps=%d draws=%d present_ms_avg=0.1 present_ms_max=0.2 gpu_ms=1.0 decode_ms_avg=0.0 " \
           "giant_wait_ms=1.0 giant_hold_ms=2.0 giant_acq=10" % (t, fps, draws)


def fs_line(t, mode, fps, speed):
    return "%8.2f [FRAMESTEP] policy=auto-m mode_word=%d decision=%d frames=1 ticks=10 game_s/wall_s=0.9 " \
           "win_fps=%.1f win_speed=%.3f hist k1/k2/k3/other=1/0/0/0" % (t, mode, mode, fps, speed)


def synth(level_ls, end, fps, ticks_per_frame=None, mode=None, crash=False):
    """Title noise + hub .ls + level .ls at level_ls; one [FPS] per second until end (constant fps);
    [FRAMESTEP] each second if mode is not None (speed = fps*ticks/600)."""
    L = ["T0 1000.000", "%8.2f %s" % (0.5, LS % 1), "%8.2f %s" % (33.0, LS % 2), "%8.2f %s" % (level_ls, LS % 3)]
    t = 40
    while t <= end:
        f = fps if t >= level_ls + 20 else 5      # the load / first 20 s after the level .ls are not gameplay
        L.append(fps_line(t + 0.1, f, 250 if t < level_ls + 5 else 150))
        if mode is not None:
            L.append(fs_line(t + 0.2, mode, f, f * ticks_per_frame / 600.0))
        t += 1
    if crash:
        L.append("%8.2f [CRASH] ===== fatal signal =====" % end)
    return "\n".join(L) + "\n"


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def put(self, tag, text, meta="alive_at_stop=1\ndone after 400s\n"):
        for ext, body in (("log", text), ("meta", meta)):
            with open(os.path.join(self.d, "lp_%s.%s" % (tag, ext)), "w") as fh:
                fh.write(body)

    def test_landmark_and_windows(self):
        self.put("a", synth(70.0, 70 + 260, 60, 10, mode=1))
        r = fs_an.an(self.d, "a")
        self.assertAlmostEqual(r["level_ls"], 70.0)
        self.assertEqual(r["speed_src"], "framestep")
        # gameplay window = level + 20 -> end (cap 330): 240 s of data -> 8 windows of 30 s
        self.assertEqual(len(r["windows"]), 8)
        for w in r["windows"]:
            self.assertAlmostEqual(w["speed"], 60 * 10 / 600.0, places=2)
            self.assertAlmostEqual(w["fps"], 60, places=1)
        self.assertTrue(r["all_speed_ok"])
        self.assertEqual(r["mode_words"], [1])

    def test_speed_fails_outside_two_percent(self):
        # a machine at 24 fps in mode 1 (10 ticks): speed 0.4 -> not ok
        self.put("a", synth(70.0, 330, 24, 10, mode=1))
        r = fs_an.an(self.d, "a")
        self.assertFalse(r["all_speed_ok"])
        self.assertAlmostEqual(r["speed_min"], 0.4, places=2)
        # a 30 s window with speed 0.98 is ok, 0.97 is not
        self.put("b", synth(70.0, 330, 29.4, 20, mode=0))   # 0.98
        self.assertTrue(fs_an.an(self.d, "b")["all_speed_ok"])
        self.put("c", synth(70.0, 330, 29.1, 20, mode=0))   # 0.97
        self.assertFalse(fs_an.an(self.d, "c")["all_speed_ok"])

    def test_off_arm_speed_is_inferred_from_fps_and_20_ticks(self):
        self.put("o", synth(70.0, 330, 24))
        r = fs_an.an(self.d, "o")
        self.assertEqual(r["speed_src"], "inferred20")
        self.assertAlmostEqual(r["windows"][0]["speed"], 24 * 20 / 600.0, places=3)
        self.assertFalse(r["all_speed_ok"])

    def test_control_comparison(self):
        self.put("o1", synth(70.2, 330, 24))
        self.put("o2", synth(70.9, 330, 25))
        self.put("a1", synth(77.3, 330, 24, 10, mode=1))
        self.put("a2", synth(70.5, 330, 24, 10, mode=1))
        c = fs_an.compare(self.d, ["a1", "a2"], ["o1", "o2"])
        self.assertAlmostEqual(c["a1"]["landmark_delta_s"], 77.3 - 70.55, places=2)
        self.assertFalse(c["a1"]["landmark_ok"])
        self.assertTrue(c["a2"]["landmark_ok"])
        self.assertAlmostEqual(c["noise_floor_s"], 0.7, places=2)          # OFF vs OFF spread
        # fps: auto avg vs OFF avg
        self.assertAlmostEqual(c["a1"]["fps_vs_control"], 24 - 24.5, places=2)
        self.assertFalse(c["a1"]["fps_ok"])   # auto fps (24.0) < control (24.5)
        # speed ratio auto/OFF = (24*10) / (24.5*20)
        self.assertAlmostEqual(c["a1"]["speed_ratio"], (24 * 10) / (24.5 * 20), places=2)

    def test_invalid_run_without_level_and_crash_flag(self):
        self.put("x", "T0 1.0\n   1.00 [FPS] fps=30 draws=3 giant_wait_ms=1 giant_hold_ms=1 giant_acq=1\n")
        self.assertFalse(fs_an.an(self.d, "x")["valid"])
        self.put("y", synth(70.0, 330, 30, 20, mode=0, crash=True),
                 meta="alive_at_stop=0 (process exited on its own)\n")
        r = fs_an.an(self.d, "y")
        self.assertEqual(r["crash"], 1)
        self.assertFalse(r["alive_at_stop"])

    def test_short_run_has_fewer_windows(self):
        self.put("s", synth(70.0, 70 + 20 + 65, 30, 20, mode=0))   # 65 s of gameplay -> 2 full windows
        self.assertEqual(len(fs_an.an(self.d, "s")["windows"]), 2)


if __name__ == "__main__":
    unittest.main()
