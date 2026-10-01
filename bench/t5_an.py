#!/usr/bin/env python3
"""A/B de PS3_JC_WORKERS no modo de 60 Hz do jogo (plano 60 fps, Tarefa 5), janelas por EVENTO.

uso: t5_an.py <dir> <tag>...      le <dir>/lp_<tag>.log/.meta/.thr (saida do bench/run_lp.sh) e <tag>.reg (opcional)

Janela de gameplay = primeiro `.ls` do nivel (LoadingScreens/*.ls com t > 55 s) + 20 s -> ultimo [FPS] (mesma do fs_an.py).
Por corrida (uma linha, chave=valor):
  fps_avg      media dos fps por segundo na janela (NAO a mediana)
  ft_p50/p95/p99  FRAMETIME: p50 = mediana dos p50 por segundo; p95/p99 = MEDIA dos p95/p99 por segundo (aproximacao do
                  percentil agrupado: o log so tem percentis por segundo); ft_p95_max_s = pior p95 de um segundo
  us_job_844e80   ms/jobs somados nas janelas [JCPAR] da janela de gameplay (pondera por jobs)
  chain_ms_f      parede do chain por quadro = seg_wall_ms/quadros (workers>1) ou serial_ms/quadros (walker serial)
  serial_ms_f     soma dos tempos de job por quadro (o custo que o paralelismo divide)
  hold_ms_f       giant_hold_ms por quadro (media de giant_hold_ms[s]/fps[s]); wait_ms_f idem para giant_wait_ms
  decode_ms_f     decode_ms_avg do [FPS] (decode do FIFO por quadro)
  gpu_ms          gpu_ms do [FPS] (media)
  skip_pct        [AUDIO] pulados somados / (188 blocos/s x segundos da janela); falta = soma de `falta`
  speed           media de win_speed do [FRAMESTEP]; mode1_pct = % dos [FRAMESTEP] da janela com mode_word=1
  workers_line    texto da linha `[jobchain] chain ...: N job workers (requested ...)` (ausente no walker serial, N=1)
  pcore_med/min   fatia de P-cores do processo (.thr) na janela
  reg_gt100       amostras de 5 s da janela em que um processo que nao e' o jogo passou de 100% de CPU (criterio de exclusao)
  reg_*           regime: carga, swap, maior processo nao-jogo (do <tag>.reg amostrado a cada 5 s), em % de CPU
"""
import re
import statistics as st
import sys

BLOCKS_S = 188.0
GAME_START_S = 20.0


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def an(P, tag):
    fps = {}
    ft = {}
    aud = {}
    fs = {}
    ls = []
    jc = []                 # (t, chain, win, jobs, serial_ms, workers, seg_wall_ms, {bin: (jobs, ms)})
    workers_line = None
    crash = 0
    t0 = None
    last_jc = None
    with open("%s/lp_%s.log" % (P, tag), errors="replace") as fh:
        for l in fh:
            if l.startswith("T0 "):
                t0 = float(l.split()[1])
                continue
            m = re.match(r"\s*([\d.]+) (.*)", l)
            if not m:
                continue
            t = float(m.group(1))
            r = m.group(2)
            s = int(t)
            if r.startswith("[FPS]"):
                f = re.search(r"fps=(\d+) draws=(\d+) .*?gpu_ms=([\d.]+) decode_ms_avg=([\d.]+) "
                              r"giant_wait_ms=([\d.]+) giant_hold_ms=([\d.]+)", r)
                if f:
                    fps[s] = (int(f.group(1)), int(f.group(2)), float(f.group(3)), float(f.group(4)),
                              float(f.group(5)), float(f.group(6)))
            elif r.startswith("[FRAMETIME]"):
                q = re.search(r"p50_ms=([\d.]+) p95_ms=([\d.]+) p99_ms=([\d.]+) max_ms=([\d.]+)", r)
                if q:
                    ft[s] = tuple(float(x) for x in q.groups())
            elif r.startswith("[AUDIO]"):
                a = re.search(r"pulados=(\d+).*falta=(\d+)", r)
                if a:
                    aud[s] = (int(a.group(1)), int(a.group(2)))
            elif r.startswith("[FRAMESTEP] policy"):
                w = re.search(r"win_speed=([\d.]+)", r)
                mw = re.search(r"mode_word=(-?\d+)", r)
                if w:
                    fs[s] = (float(w.group(1)), int(mw.group(1)) if mw else None)
            elif r.startswith("[JCPAR] chain="):
                j = re.search(r"chain=(\S+) win=([\d.]+)s maxCont=(\d+) jobs=(\d+) serial_ms=(\d+)", r)
                if j:
                    last_jc = [t, j.group(1), float(j.group(2)), int(j.group(4)), int(j.group(5)), 1, None, {}]
                    jc.append(last_jc)
            elif r.startswith("[JCPAR]   workers=") and last_jc is not None:
                w = re.search(r"workers=(\d+) seg_wall_ms=(\d+)", r)
                if w:
                    last_jc[5] = int(w.group(1))
                    last_jc[6] = int(w.group(2))
            elif r.startswith("[JCPAR]   bin=") and last_jc is not None:
                b = re.search(r"bin=0x([0-9A-Fa-f]+) jobs=(\d+) ms=(\d+)", r)
                if b:
                    last_jc[7][b.group(1).upper().lstrip("0")] = (int(b.group(2)), int(b.group(3)))
            elif "job workers (requested" in r and workers_line is None:
                workers_line = r.strip()
            elif "[CRASH]" in r:
                crash += 1
            elif "LoadingScreens/" in r and ".ls'" in r and "open" in r:
                ls.append(t)
    res = {"tag": tag, "valid": False, "crash": crash}
    lv = [x for x in ls if x > 55]
    if not lv or not fps:
        return res
    L = lv[0]
    G = L + GAME_START_S
    last = max(fps)
    gp = [s for s in range(int(G) + 1, last + 1) if s in fps and fps[s][1] >= 100]
    res["level_ls"] = round(L, 1)
    res["win_s"] = len(gp)
    res["valid"] = len(gp) >= 150
    if not gp:
        return res
    res["fps_avg"] = round(_mean(fps[s][0] for s in gp), 2)
    res["fps_median"] = st.median(fps[s][0] for s in gp)
    fts = [ft[s] for s in gp if s in ft]
    if fts:
        res["ft_p50"] = round(st.median(x[0] for x in fts), 2)
        res["ft_p95"] = round(_mean(x[1] for x in fts), 2)
        res["ft_p95_med"] = round(st.median(x[1] for x in fts), 2)
        res["ft_p99"] = round(_mean(x[2] for x in fts), 2)
        res["ft_p95_max_s"] = round(max(x[1] for x in fts), 2)
        res["ft_max"] = round(max(x[3] for x in fts), 2)
    hold = [fps[s][5] / fps[s][0] for s in gp if fps[s][0]]
    wait = [fps[s][4] / fps[s][0] for s in gp if fps[s][0]]
    res["hold_ms_f"] = round(_mean(hold), 2)
    res["wait_ms_f"] = round(_mean(wait), 2)
    res["decode_ms_f"] = round(_mean(fps[s][3] for s in gp), 2)
    res["gpu_ms"] = round(_mean(fps[s][2] for s in gp), 2)
    secs = len(gp)
    res["skip_pct"] = round(100.0 * sum(aud.get(s, (0, 0))[0] for s in gp) / (BLOCKS_S * secs), 3)
    res["falta"] = sum(aud.get(s, (0, 0))[1] for s in gp)
    sp = [fs[s] for s in gp if s in fs]
    if sp:
        res["speed"] = round(_mean(x[0] for x in sp), 3)
        m1 = [x for x in sp if x[1] is not None]
        res["mode1_pct"] = round(100.0 * sum(1 for x in m1 if x[1] == 1) / len(m1), 1) if m1 else float("nan")
    # JCPAR windows entirely inside the gameplay window
    wins = [x for x in jc if x[0] - x[2] >= G and x[0] <= last + 1 and x[3] > 0]
    if wins:
        chains = sorted(set(x[1] for x in wins))
        res["jcpar_n"] = len(wins)
        res["chains"] = ",".join(chains)
        fr = 0
        jobs = ms = 0
        wall = ser = 0.0
        b_j = b_ms = 0
        for x in wins:
            a, b = int(x[0] - x[2]) + 1, int(x[0])
            f = sum(fps[s][0] for s in range(a, b + 1) if s in fps)
            fr += f
            jobs += x[3]
            ser += x[4]
            wall += x[6] if x[6] is not None else x[4]     # serial walker: wall = job time
            if "844E80" in x[7]:
                b_j += x[7]["844E80"][0]
                b_ms += x[7]["844E80"][1]
        if fr:
            res["chain_ms_f"] = round(wall / fr, 2)
            res["serial_ms_f"] = round(ser / fr, 2)
            res["jobs_f"] = round(jobs / fr, 1)
        if b_j:
            res["us_job_844e80"] = round(1000.0 * b_ms / b_j, 1)
        res["workers"] = wins[0][5]
    res["workers_line"] = workers_line or "(none: serial walker)"
    # thrmon
    if t0 is not None:
        pc = []
        try:
            with open("%s/lp_%s.thr" % (P, tag)) as fh:
                for l in fh:
                    p = l.split(" ", 1)
                    t = float(p[0]) - t0
                    if G <= t <= last + 1:
                        mm = re.search(r"pcore=([\d.-]+)", p[1])
                        if mm:
                            pc.append(float(mm.group(1)))
        except (FileNotFoundError, ValueError):
            pass
        if pc:
            res["pcore_med"] = round(st.median(pc), 2)
            res["pcore_min"] = round(min(pc), 2)
        # regime sampler: <tag>.reg lines "<epoch> load=a b c swap=NM top: cpu:comm ..."
        try:
            top1 = []
            loads = []
            swaps = []
            with open("%s/lp_%s.reg" % (P, tag)) as fh:
                for l in fh:
                    p = l.split(" ", 1)
                    t = float(p[0]) - t0
                    if not (G <= t <= last + 1):
                        continue
                    mm = re.search(r"top: (\S+)", l)
                    if mm:
                        c, _, name = mm.group(1).partition(":")
                        top1.append((float(c.replace(",", ".")), name))
                    mm = re.search(r"load=\s*(\S+)", l)
                    if mm:
                        loads.append(float(mm.group(1).replace(",", ".")))
                    mm = re.search(r"swap=([\d.,]+)M", l)
                    if mm:
                        swaps.append(float(mm.group(1).replace(".", "").replace(",", ".")))
            if top1:
                worst = max(top1)
                res["reg_top1_max"] = "%.0f%%:%s" % worst
                res["reg_top1_med"] = round(st.median(x[0] for x in top1), 1)
                hot = [x for x in top1 if x[0] > 100.0]
                res["reg_gt100"] = "%d/%d" % (len(hot), len(top1))      # samples (5 s) with an outside process > 100% CPU
                res["reg_gt100_names"] = ",".join(sorted(set(x[1] for x in hot))) or "-"
            if loads:
                res["reg_load1_med"] = round(st.median(loads), 2)
            if swaps:
                res["reg_swap_mb"] = "%.0f->%.0f" % (swaps[0], swaps[-1])
        except (FileNotFoundError, ValueError):
            pass
    return res


if __name__ == "__main__":
    for tg in sys.argv[2:]:
        out = an(sys.argv[1], tg)
        print(" ".join("%s=%s" % (k, v) for k, v in out.items()))
