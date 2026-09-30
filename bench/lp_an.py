#!/usr/bin/env python3
"""Load/audio analysis of a run log, windows by EVENT (not by clock).

usage: lp_an.py <dir> <tag>...      reads <dir>/lp_<tag>.log (run_lp.sh output)

Level load  = first '.ls' open after t>55 s  ->  first [FPS] second with draws>=100 (after L+1).
Hub load    = first '.ls' open at 10<t<=55 s (5 s window for the skip %).
Valid run   = level .ls seen AND >= 20 s of draws>=100 after the load; otherwise INVALID
              (an invalid run is excluded, never read as "no effect").
Skip %      = [AUDIO] pulados summed over the window / (188 blocks/s * window seconds).
"""
import re,sys,statistics as st
def an(P,tag):
    fps={};aud={};gs={};ft={};ls=[];t0=None
    for l in open(f"{P}/lp_{tag}.log",errors="replace"):
        if l.startswith("T0 "): t0=float(l.split()[1]); continue
        m=re.match(r"\s*([\d.]+) (.*)",l)
        if not m: continue
        tf=float(m.group(1)); s=int(tf); r=m.group(2)
        f=re.search(r"\[FPS\] fps=(\d+) draws=(\d+).*giant_wait_ms=([\d.]+) giant_hold_ms=([\d.]+) giant_acq=(\d+)",r)
        if f: fps[s]=(int(f.group(1)),int(f.group(2)),float(f.group(3)),float(f.group(4)),int(f.group(5)))
        a=re.search(r"\[AUDIO\].*espera=(\d+) pulados=(\d+).*falta=(\d+)",r)
        if a: aud[s]=(int(a.group(1)),int(a.group(2)),int(a.group(3)))
        g=re.search(r"\[GIANTSTAT\].*max_wait_ms=([\d.]+) slow_acq=(\d+) max_hold_ms=([\d.]+).*handoffs=(\d+)",r)
        if g: gs[s]=(float(g.group(1)),int(g.group(2)),float(g.group(3)),int(g.group(4)))
        q=re.search(r"\[FRAMETIME\].*?p50_ms=([\d.]+).*?p99_ms=([\d.]+).*?max_ms=([\d.]+)",r)
        if q: ft[s]=(float(q.group(1)),float(q.group(2)),float(q.group(3)))
        if "LoadingScreens/" in r and ".ls'" in r and "open" in r: ls.append(tf)
    lv=[x for x in ls if x>55]; hub=[x for x in ls if 10<x<=55]
    res={"tag":tag}
    if not lv: res["valid"]=False; return res
    L=lv[0]; E=next((s for s in sorted(fps) if s>L+1 and fps[s][1]>=100),None)
    if E is None: res["valid"]=False; return res
    gp=[s for s in fps if E+3<=s<=E+30]
    res["valid"]=len([s for s in fps if s>=E and fps[s][1]>=100])>=20
    res["level_ls"]=L; res["load_s"]=E-L
    win=range(int(L),E+1)
    blocks=188*len(win)
    res["load_skip"]=sum(aud.get(s,(0,0,0))[1] for s in win); res["load_skip_pct"]=100*res["load_skip"]/blocks
    res["load_fps"]=st.mean([fps[s][0] for s in win if s in fps] or [-1])
    res["load_gwait_ms_s"]=st.mean([fps[s][2] for s in win if s in fps] or [-1])
    res["load_gmaxwait"]=max((gs[s][0] for s in win if s in gs),default=-1)
    res["load_gmaxwait_med"]=st.median([gs[s][0] for s in win if s in gs] or [-1])
    res["load_gmaxhold_med"]=st.median([gs[s][2] for s in win if s in gs] or [-1])
    if hub:
        H=hub[0]; hw=range(int(H),int(H)+5)
        res["hub_skip_pct"]=100*sum(aud.get(s,(0,0,0))[1] for s in hw)/(188*5)
    res["gp_fps"]=st.median(fps[s][0] for s in gp) if gp else -1
    res["gp_skip"]=sum(aud.get(s,(0,0,0))[1] for s in gp)
    res["gp_gwait_ms_s"]=st.mean(fps[s][2] for s in gp) if gp else -1
    res["gp_gmaxwait_med"]=st.median([gs[s][0] for s in gp if s in gs] or [-1])
    res["gp_ft_p99_med"]=st.median([ft[s][1] for s in gp if s in ft] or [-1])
    res["falta"]=sum(v[2] for v in aud.values())
    return res
if __name__=="__main__":
  for t in sys.argv[2:]:
    r=an(sys.argv[1],t); print(" ".join(f"{k}={v:.1f}" if isinstance(v,float) else f"{k}={v}" for k,v in r.items()))
