#!/usr/bin/env python3
"""Tarefa 6 (plano 60 fps): por corrida, a inflacao por job a partir das sondas PS3_TRACE_JC_PHASE / PS3_TRACE_ATOMIC_LINE / thrmon.

uso: t6_an.py <dir> <tag>... [--bins]    le <dir>/lp_<tag>.log e .thr (saida do bench/run_lp.sh com PS3_TRACE_JC_PAR=1 PS3_TRACE_JC_PHASE=1)

Janela de gameplay = primeiro `.ls` do nivel (t > 55 s) + 20 s -> fim; so entram as janelas [JCPH] impressas a partir de .ls + 30 s (cada uma
cobre os 10 s anteriores). Por corrida: fps medio, jobs/quadro, ms de job/quadro, Minstrucoes/quadro, e por job: parede, CPU, preparo, kcycles,
kinstrucoes, IPC, GHz efetivo (ciclos / CPU da thread), tambem por binario (--bins) e por concorrencia k; GHz/IPC/P-core/thermal do processo
(.thr), contagem do mutex da linha de reserva ([ATOMLINE]) e dos mutexes do job chain ([JCLOCK]).
"""
import re, sys, statistics as st
def kv(line):
    d = {}
    for m in re.finditer(r"(\w+(?:/\w+)?)=([-\d.]+)", line): d[m.group(1)] = float(m.group(2))
    return d
def an(P, tag, bins=False):
    ls = None; fps = []; jc = []; locks = []; atl = []; thr = []; skip = 0; t0 = None; frames_by_s = {}
    gh = []
    with open(f"{P}/lp_{tag}.log", errors="replace") as fh:
        for l in fh:
            if l.startswith("T0 "): t0 = float(l.split()[1]); continue
            m = re.match(r"\s*([\d.]+) (.*)", l)
            if not m: continue
            t = float(m.group(1)); r = m.group(2)
            if ls is None and t > 55 and re.search(r"LoadingScreens/.*\.ls'", r): ls = t
            if r.startswith("[FPS]"):
                f = re.search(r"fps=(\d+) draws=(\d+).*giant_wait_ms=([\d.]+) giant_hold_ms=([\d.]+)", r)
                d = re.search(r"decode_ms_avg=([\d.]+)", r)
                if f: fps.append((t, int(f.group(1)), int(f.group(2)), float(f.group(3)), float(f.group(4)), float(d.group(1)) if d else 0))
            elif r.startswith("[JCPH]"):
                b = re.search(r"bin=0x([0-9A-Fa-f]+) k=(\d+)", r); d = kv(r); d["bin"] = b.group(1).lstrip("0").upper(); d["k"] = int(b.group(2)); d["t"] = t; jc.append(d)
            elif r.startswith("[JCLOCK]"):
                locks.append((t, r))
            elif r.startswith("[ATOMLINE]"):
                atl.append((t, kv(r)))
            elif r.startswith("[AUDIO]"):
                pass
    if ls is None: return None
    w0 = ls + 30   # JCPH window printed at >= ls+30 covers >= ls+20
    gp = [x for x in fps if x[0] >= ls + 20 and x[2] >= 100]
    out = {"tag": tag, "ls": ls, "fps_avg": st.mean(x[1] for x in gp) if gp else float("nan"), "secs": len(gp)}
    out["hold_ms_s"] = st.mean(x[4] for x in gp) if gp else 0
    out["wait_ms_s"] = st.mean(x[3] for x in gp) if gp else 0
    out["decode_ms"] = st.mean(x[5] for x in gp) if gp else 0
    frames = sum(x[1] for x in gp)
    sel = [d for d in jc if d["t"] >= w0]
    out["jc_windows"] = len({d["t"] for d in sel})
    def agg(ds):
        n = sum(d["jobs"] for d in ds)
        if not n: return None
        s = lambda f: sum(d[f] * d["jobs"] for d in ds if f in d)
        a = {"jobs": n}
        for f in ("wall_us", "cpu_us", "prep_us", "run_wall_us", "run_cpu_us", "run_kcyc", "run_kins", "prep_kcyc", "atl_acq/job", "atl_cont/job", "atl_wait_us/job", "kend"):
            a[f] = s(f) / n
        a["ipc"] = a["run_kins"] / a["run_kcyc"] if a["run_kcyc"] else 0
        a["ghz"] = a["run_kcyc"] / (a["run_cpu_us"]) if a["run_cpu_us"] else 0
        return a
    out["all"] = agg(sel)
    out["bins"] = {}
    for b in sorted({d["bin"] for d in sel}): out["bins"][b] = agg([d for d in sel if d["bin"] == b])
    out["byk"] = {}
    for b in ("844E80",):
        for k in range(1, 9):
            a = agg([d for d in sel if d["bin"] == b and d["k"] == k])
            if a: out["byk"][k] = a
    # per-frame: windows are ~10 s; frames = fps avg * 10 s * windows
    nwin = out["jc_windows"]
    out["frames_win"] = out["fps_avg"] * 10.0 * nwin
    if out["all"] and out["frames_win"]:
        a = out["all"]
        out["jobs_per_frame"] = a["jobs"] / out["frames_win"]
        out["job_ms_per_frame"] = a["jobs"] * a["wall_us"] / 1e3 / out["frames_win"]
        out["kins_per_frame"] = a["jobs"] * a["run_kins"] / out["frames_win"]
    # lock lines
    sl = [r for t, r in locks if t >= w0]
    out["lock_lines"] = len(sl)
    def lsum(name):
        a = c = w = 0.0
        for r in sl:
            m = re.search(name + r" acq=(\d+) cont=(\d+) wait_ms=([\d.]+)", r)
            if m: a += int(m.group(1)); c += int(m.group(2)); w += float(m.group(3))
        return a, c, w
    out["locks"] = {n: lsum(n) for n in ("fp_mu", "evq_mx", "pool_mu")}
    idle = 0.0
    for r in sl:
        m = re.search(r"idle_ms=([\d.]+)", r); idle += float(m.group(1)) if m else 0
    out["idle_ms"] = idle
    sa = [x for t, x in atl if t >= w0]
    out["atl"] = (sum(x["acq"] for x in sa), sum(x["contended"] for x in sa), sum(x["wait_ms"] for x in sa))
    # thr
    try:
        g = []; pc = []; ip = []; tot = []; th = []
        for l in open(f"{P}/lp_{tag}.thr"):
            m = re.match(r"([\d.]+) \[THR\] t=([\d.]+) tot_ms=(\d+) pcore=([-\d.]+) ghz=([-\d.]+) ipc=([-\d.]+)(?: therm=(-?\d+))?", l)
            if not m: continue
            ep = float(m.group(1))
            if t0 and ep - t0 >= ls + 20 and float(m.group(5)) > 0 and int(m.group(3)) < 1e8:
                th.append(int(m.group(7)) if m.group(7) else -1); g.append(float(m.group(5))); pc.append(float(m.group(4))); ip.append(float(m.group(6))); tot.append(int(m.group(3)))
        out["proc_ghz"] = st.mean(g) if g else 0; out["proc_ipc"] = st.mean(ip) if ip else 0
        out["pcore"] = st.mean(pc) if pc else 0; out["cpu_cores"] = st.mean(tot) / 1000.0 if tot else 0
        out["therm_max"] = max(th) if th else -1; out["ghz_first"] = st.mean(g[:8]) if g else 0; out["ghz_last"] = st.mean(g[-8:]) if g else 0
    except FileNotFoundError: pass
    return out
def fmt(o, bins=False):
    if not o: return "(no level)"
    a = o["all"]
    s = (f"{o['tag']}: fps={o['fps_avg']:.1f} ({o['secs']}s) jobs/f={o.get('jobs_per_frame',0):.0f} jobms/f={o.get('job_ms_per_frame',0):.1f} Minst/f={o.get('kins_per_frame',0)/1e3:.1f} "
         f"| all-bins us/job wall={a['wall_us']:.0f} cpu={a['cpu_us']:.0f} prep={a['prep_us']:.1f} kcyc={a['run_kcyc']:.0f} kins={a['run_kins']:.0f} ipc={a['ipc']:.2f} ghz(run)={a['ghz']:.2f} "
         f"| proc ghz={o.get('proc_ghz',0):.2f} (first8 {o.get('ghz_first',0):.2f} last8 {o.get('ghz_last',0):.2f}) ipc={o.get('proc_ipc',0):.2f} pcore={o.get('pcore',0):.2f} therm_max={o.get('therm_max',-1)} cores={o.get('cpu_cores',0):.2f} "
         f"| hold={o['hold_ms_s']:.0f}ms/s decode={o['decode_ms']:.2f}")
    s += "\n   844E80 " + (f"us/job wall={o['bins']['844E80']['wall_us']:.0f} kcyc={o['bins']['844E80']['run_kcyc']:.0f} kins={o['bins']['844E80']['run_kins']:.0f} ipc={o['bins']['844E80']['ipc']:.2f} ghz={o['bins']['844E80']['ghz']:.2f}" if "844E80" in o["bins"] else "none")
    s += f"\n   atl(acq,cont,wait_ms)={o['atl']} locks=" + " ".join(f"{k}:{int(v[0])}/{int(v[1])}/{v[2]:.1f}ms" for k, v in o["locks"].items()) + f" worker_idle_ms={o['idle_ms']:.0f} windows={o['jc_windows']}"
    if bins:
        for b, x in o["bins"].items(): s += f"\n   bin {b}: jobs={x['jobs']:.0f} wall={x['wall_us']:.1f} cpu={x['cpu_us']:.1f} prep={x['prep_us']:.1f} kcyc={x['run_kcyc']:.0f} kins={x['run_kins']:.0f} ipc={x['ipc']:.2f} ghz={x['ghz']:.2f} atl/job={x['atl_acq/job']:.2f}"
        for k, x in o["byk"].items(): s += f"\n   844E80 k={k}: jobs={x['jobs']:.0f} wall={x['wall_us']:.0f} kins={x['run_kins']:.0f} ipc={x['ipc']:.2f} ghz={x['ghz']:.2f}"
    return s
if __name__ == "__main__":
    P = sys.argv[1]; tags = [a for a in sys.argv[2:] if not a.startswith("--")]; b = "--bins" in sys.argv
    for t in tags: print(fmt(an(P, t, b), b))
