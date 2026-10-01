#!/usr/bin/env python3
"""Teste do bench/t5_an.py com log sintetico.  Rodar: python3 bench/test_t5_an.py

Log: nivel .ls em t=70.10; gameplay = 90.10 -> 129. fps alterna 40/60 (media 50, mediana 50 ou 60 conforme a contagem),
giant_hold_ms/fps != media direta, [JCPAR] com workers (seg_wall_ms) e serial, [AUDIO] pulados, [FRAMESTEP]."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t5_an  # noqa: E402


def synth(workers=5, last_s=129, mode_word=1):
    lines = ["T0 1000.000",
             "   70.10 [fs] open '/dev_bdvd/PS3_GAME/USRDIR/LoadingScreens/x.ls' -> fd 3 (lr=0x2EC00)"]
    if workers > 1:
        lines.append("   70.20 [jobchain] chain 0x400D2200: %d job workers (requested %d, maxContention 6, nSpus 5)"
                     % (workers, workers))
    for s in range(60, last_s + 1):
        gp = s >= 90
        fps = 60 if (s % 3 == 0) else 30        # gameplay mean 40, median 30 (the median must NOT be reported)
        draws = 3 if 70 <= s <= 73 else 250
        t = s + 0.43
        lines.append("%8.2f [FPS] fps=%d draws=%d present_ms_avg=0.6 present_ms_max=0.7 gpu_ms=7.00 "
                     "decode_ms_avg=4.00 giant_wait_ms=300.0 giant_hold_ms=%.1f giant_acq=5000" % (t, fps, draws, 10.0 * fps))
        lines.append("%8.2f [FRAMETIME] n=%d p50_ms=20.00 p95_ms=%.2f p99_ms=30.00 max_ms=35.00 over33=1 over50=0 over100=0"
                     % (t, fps, 25.0 if gp else 90.0))
        lines.append("%8.2f [AUDIO] t=1.0 blocos=188 pico=0 cru=0 espera=0 pulados=%d perdidos=0 falta=%d anel=1 portos=1/1 mudo=1"
                     % (t, 2 if gp else 40, 1 if gp else 0))
        lines.append("%8.2f [FRAMESTEP] policy=60 mode_word=%d decision=1 frames=1 ticks=10 game_s/wall_s=0.5 win_fps=%d "
                     "win_speed=%.3f hist k1/k2/k3/other=1/0/0/0" % (t, mode_word if gp else 0, fps, fps / 60.0))
    # two [JCPAR] windows (10 s each) inside the gameplay window, one before it (must be ignored)
    for tj, bad in ((85.0, True), (105.0, False), (115.0, False)):
        jobs = 1000 if bad else 2000
        lines.append("%8.2f [JCPAR] chain=0x400D2200 win=10.0s maxCont=6 jobs=%d serial_ms=%d (100.0%% of wall) lb2_ms=1 lb3_ms=1 "
                     "lb5_ms=1 segs=1 jobs/seg[1,2-3,4-7,8+]=1,1,1,1 jts_waits=1 jts_ms=1 guard_ms=1" % (tj, jobs, 4000 if not bad else 99999))
        if workers > 1:
            lines.append("%8.2f [JCPAR]   workers=%d seg_wall_ms=%d" % (tj, workers, 1000 if not bad else 99999))
        lines.append("%8.2f [JCPAR]   bin=0x00844E80 jobs=%d ms=%d us/job=1.0" % (tj, jobs, 600 if not bad else 99999))
        lines.append("%8.2f [JCPAR]   bin=0x00843080 jobs=10 ms=5000 us/job=1.0" % tj)
    return "\n".join(lines) + "\n"


class T(unittest.TestCase):
    def run_log(self, text, reg=None):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "lp_t.log"), "w") as f:
                f.write(text)
            if reg:
                with open(os.path.join(d, "lp_t.reg"), "w") as f:
                    f.write(reg)
            return t5_an.an(d, "t")

    def test_window_and_means(self):
        r = self.run_log(synth())
        self.assertFalse(r["valid"])                    # 39 s of gameplay < 150 s: excluded, never read as 'no effect'
        self.assertAlmostEqual(r["level_ls"], 70.1, places=1)
        # window 91..129 = 39 s; fps = 60 on s%3==0 (13 s), 30 otherwise (26 s) -> mean 40.0 (median would be 30)
        self.assertEqual(r["win_s"], 39)
        self.assertAlmostEqual(r["fps_avg"], 40.0, places=1)
        self.assertEqual(r["fps_median"], 30)
        self.assertEqual(r["ft_p95"], 25.0)            # the pre-gameplay 90 ms seconds are outside the window
        self.assertEqual(r["ft_p50"], 20.0)

    def test_per_frame_stages(self):
        r = self.run_log(synth())
        self.assertAlmostEqual(r["hold_ms_f"], 10.0, places=2)     # giant_hold_ms / fps, per second
        self.assertAlmostEqual(r["wait_ms_f"], _mean_wait(), places=2)
        self.assertEqual(r["decode_ms_f"], 4.0)
        self.assertEqual(r["gpu_ms"], 7.0)
        # 2 JCPAR windows inside, frames = fps summed over the 10 s each; wall = seg_wall_ms (workers=5)
        fr = sum(60 if s % 3 == 0 else 30 for s in range(96, 106)) + sum(60 if s % 3 == 0 else 30 for s in range(106, 116))
        self.assertAlmostEqual(r["chain_ms_f"], 2000.0 / fr, places=2)
        self.assertAlmostEqual(r["serial_ms_f"], 8000.0 / fr, places=2)
        self.assertEqual(r["us_job_844e80"], 300.0)                # 1200 ms / 4000 jobs
        self.assertEqual(r["workers"], 5)
        self.assertIn("5 job workers (requested 5", r["workers_line"])

    def test_serial_walker_uses_serial_ms_as_wall(self):
        r = self.run_log(synth(workers=1))
        fr = sum(60 if s % 3 == 0 else 30 for s in range(96, 106)) + sum(60 if s % 3 == 0 else 30 for s in range(106, 116))
        self.assertAlmostEqual(r["chain_ms_f"], 8000.0 / fr, places=2)
        self.assertIn("serial", r["workers_line"])

    def test_audio_speed_mode(self):
        r = self.run_log(synth())
        self.assertAlmostEqual(r["skip_pct"], 100.0 * 2 * 39 / (188 * 39), places=2)   # 1.064 %
        self.assertEqual(r["falta"], 39)
        self.assertEqual(r["mode1_pct"], 100.0)
        self.assertAlmostEqual(r["speed"], 40.0 / 60.0, places=2)
        r0 = self.run_log(synth(mode_word=0))
        self.assertEqual(r0["mode1_pct"], 0.0)

    def test_valid_needs_150s(self):
        self.assertTrue(self.run_log(synth(last_s=260))["valid"])       # 91..260 = 170 s
        self.assertTrue(self.run_log(synth(last_s=240))["valid"])       # 91..240 = 150 s: the boundary is valid
        self.assertFalse(self.run_log(synth(last_s=239))["valid"])      # 149 s

    def test_invalid_without_level(self):
        r = self.run_log(synth().replace("LoadingScreens/x.ls", "other.bin"))
        self.assertFalse(r["valid"])

    def test_regime_sampler(self):
        reg = ("1030.0 load= 2,00 1,00 1,00  swap=8728,50M top: 150,0:Foo 20,0:Bar \n"
               "1105.0 load= 3,00 1,00 1,00  swap=8800,00M top: 12,0:Baz 5,0:Foo \n"
               "1110.0 load= 1,00 1,00 1,00  swap=8900,00M top: 30,0:Baz 5,0:Foo \n")
        r = self.run_log(synth(), reg)
        # t0 = 1000: the first sample is at t=30 (before the window G=90.1) and must be ignored
        self.assertEqual(r["reg_top1_max"], "30%:Baz")
        self.assertEqual(r["reg_swap_mb"], "8800->8900")
        self.assertEqual(r["reg_load1_med"], 2.0)


def _mean_wait():
    return sum(300.0 / (60 if s % 3 == 0 else 30) for s in range(91, 130)) / 39


if __name__ == "__main__":
    unittest.main()
