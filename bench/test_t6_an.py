#!/usr/bin/env python3
"""Teste do t6_an.py com um log sintetico: janela por evento (so [JCPH] de .ls + 30 s em diante), media ponderada por jobs, GHz = kcyc/cpu,
jobs por quadro e fatia do mutex da linha de reserva."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t6_an  # noqa: E402


def jcph(t, bin_, k, jobs, wall, cpu, kcyc, kins):
    return ("%8.2f [JCPH] bin=0x%08X k=%d jobs=%d wall_us=%.1f cpu_us=%.1f prep_us=5.0 run_wall_us=%.1f run_cpu_us=%.1f run_kcyc=%.1f "
            "run_kins=%.1f ipc=3.0 ghz=3.0 prep_kcyc=10.0 kend=%.2f atl_acq/job=0.00 atl_cont/job=0.000 atl_wait_us/job=0.00\n"
            % (t, bin_, k, jobs, wall, cpu, wall - 5, cpu - 5, kcyc, kins, k))


def main():
    d = tempfile.mkdtemp()
    log = ["T0 1000.000\n", "   60.00 open '/x/LoadingScreens/lvl.ls'\n"]
    for s in range(81, 100):                      # gameplay: 60 fps, draws >= 100
        log.append("%8.2f [FPS] fps=60 draws=200 present_ms_avg=0.6 present_ms_max=0.7 gpu_ms=6.0 decode_ms_avg=4.0 giant_wait_ms=100.0 giant_hold_ms=400.0 giant_acq=10\n" % s)
    log.append(jcph(85.0, 0x844E80, 5, 1000, 999.0, 999.0, 1.0, 1.0))      # antes de .ls + 30 s: fora da janela
    log.append(jcph(95.0, 0x844E80, 5, 3000, 300.0, 290.0, 870.0, 3480.0))  # 870 kcyc / 290 us = 3.0 GHz
    log.append(jcph(95.0, 0x844E80, 1, 1000, 100.0, 90.0, 270.0, 1080.0))   # ponderado por jobs: (3000*300 + 1000*100) / 4000 = 250
    log.append("   95.10 [ATOMLINE] win=10.0s acq=100 contended=2 (2.00%) wait_ms=1.5 wait_us/contended=750.0\n")
    log.append("   95.10 [JCLOCK] fp_mu acq=40 cont=1 wait_ms=0.10 | evq_mx acq=40 cont=0 wait_ms=0.00 | pool_mu acq=90 cont=3 wait_ms=0.50 | worker_idle waits=7 idle_ms=12.0\n")
    open(d + "/lp_x.log", "w").write("".join(log))
    o = t6_an.an(d, "x")
    assert abs(o["ls"] - 60.0) < 1e-6, o["ls"]
    a = o["all"]
    assert a["jobs"] == 4000, a                                  # a janela de 85 s ficou de fora
    assert abs(a["wall_us"] - 250.0) < 1e-6, a
    assert abs(a["run_kcyc"] - (3000 * 870 + 1000 * 270) / 4000.0) < 1e-6, a
    assert abs(a["ghz"] - a["run_kcyc"] / a["run_cpu_us"]) < 1e-9
    assert o["byk"][5]["jobs"] == 3000 and o["byk"][1]["jobs"] == 1000
    assert abs(o["fps_avg"] - 60.0) < 1e-6
    assert o["atl"] == (100, 2, 1.5), o["atl"]
    assert o["locks"]["pool_mu"] == (90, 3, 0.5), o["locks"]
    assert abs(o["idle_ms"] - 12.0) < 1e-9
    print("ok")


if __name__ == "__main__":
    main()
