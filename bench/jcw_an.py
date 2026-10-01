#!/usr/bin/env python3
"""PS3_JC_WORKERS A/B analysis (plan 2026-09-30-ben10-pipeline-opportunities, Task 4). usage: t4_an.py <dir> <tag>...  (reads lp_<tag>.log/.thr/.meta)
Gameplay window = seconds s >= max(130, E+3) (E = first [FPS] with draws>=100 after the level .ls), draws>=100 only,
to the last [FPS] second of the log. No sampled seconds exist (mode=clean)."""
import re,sys,statistics as st
def pct(v,q):
    v=sorted(v); return v[min(len(v)-1,int(q*len(v)))] if v else float('nan')
def an(P,tag):
    fps={};ft={};jc=[];ls=[]
    for l in open(f"{P}/lp_{tag}.log",errors="replace"):
        m=re.match(r"\s*([\d.]+) (.*)",l)
        if not m: continue
        t=float(m.group(1)); r=m.group(2); s=int(t)
        f=re.search(r"\[FPS\] fps=(\d+) draws=(\d+)",r)
        if f: fps[s]=(int(f.group(1)),int(f.group(2)))
        q=re.search(r"\[FRAMETIME\].*?p50_ms=([\d.]+).*?p95_ms=([\d.]+).*?p99_ms=([\d.]+).*?max_ms=([\d.]+).*?over33=(\d+)",r)
        if q: ft[s]=tuple(float(x) for x in q.groups())
        j=re.search(r"\[JCPAR\] chain=\S+ win=([\d.]+)s maxCont=(\d+) jobs=(\d+) serial_ms=(\d+)",r)
        if j: jc.append((t,float(j.group(1)),int(j.group(3)),int(j.group(4)),r))
        if r.startswith("[JCPAR]   workers="):
            w=re.search(r"workers=(\d+) seg_wall_ms=(\d+)",r)
            if w and jc: jc[-1]=jc[-1][:4]+(jc[-1][4],int(w.group(1)),int(w.group(2)))
        if "LoadingScreens/" in r and ".ls'" in r and "open" in r: ls.append(t)
    res={"tag":tag}
    lv=[x for x in ls if x>55]
    if not lv: res["valid"]=False; return res
    L=lv[0]; E=next((s for s in sorted(fps) if s>L+1 and fps[s][1]>=100),None)
    if E is None: res["valid"]=False; return res
    w0=max(130,E+3); last=max(fps)
    gp=[s for s in range(w0,last+1) if s in fps and fps[s][1]>=100]
    res["level_ls"]=round(L,1); res["E"]=E; res["win_s"]=len(gp); res["valid"]=len(gp)>=70
    res["fps_med"]=st.median(fps[s][0] for s in gp) if gp else -1
    res["fps_mean"]=round(st.mean(fps[s][0] for s in gp),2) if gp else -1
    fts=[ft[s] for s in gp if s in ft]
    res["ft_p50_med"]=st.median(x[0] for x in fts) if fts else -1
    res["ft_p99_med"]=st.median(x[2] for x in fts) if fts else -1
    res["ft_max"]=max((x[3] for x in fts),default=-1)
    res["over33_s"]=round(st.mean(x[4] for x in fts),1) if fts else -1
    jw=[x for x in jc if w0<=x[0]<=last+1 and x[2]>0]
    if jw:
        res["jcpar_n"]=len(jw)
        res["jobs_10s"]=round(st.mean(x[2] for x in jw))
        res["serial_ms_10s"]=round(st.mean(x[3] for x in jw))
        sw=[x[6] for x in jw if len(x)>6]
        if sw: res["seg_wall_ms_10s"]=round(st.mean(sw)); res["workers"]=jw[0][5]
    # thrmon
    t0=None
    for l in open(f"{P}/lp_{tag}.log",errors="replace"):
        if l.startswith("T0 "): t0=float(l.split()[1]); break
    q_=[];tot=[];spw=[];pc=[]
    try:
        for l in open(f"{P}/lp_{tag}.thr"):
            p=l.split(" ",1); t=float(p[0])-t0
            if w0<=t<=last+1:
                m=re.search(r"\? x\d+=(\d+)",p[1]); q_.append(int(m.group(1)) if m else 0)
                m=re.search(r"tot_ms=(\d+)",p[1]); tot.append(int(m.group(1)))
                m=re.search(r"pcore=([\d.-]+)",p[1]); pc.append(float(m.group(1)))
                m=re.search(r"host:spurs-worker x5=(\d+)",p[1]); spw.append(int(m.group(1)) if m else 0)
        res["unnamed_thr_cpu_ms_s"]=round(st.median(q_)) if q_ else -1
        res["proc_cpu_ms_s"]=round(st.median(tot)) if tot else -1
        res["spurs_workers_ms_s"]=round(st.median(spw)) if spw else -1
        res["pcore_min"]=min(pc) if pc else -1; res["pcore_med"]=st.median(pc) if pc else -1
    except FileNotFoundError: pass
    return res
if __name__=="__main__":
    for t in sys.argv[2:]:
        r=an(sys.argv[1],t); print(" ".join(f"{k}={v}" for k,v in r.items()))
