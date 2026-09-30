#!/usr/bin/env python3
"""Audio continuity by phase (TITULO / CARGA / OUTRO / GAMEPLAY) from <dir>/<tag>.log.
usage: phases.py <dir> <tag>...   CARGA = the 4 s after every '.ls' open (t>10 s); valid = >=60 s gameplay.
NOTE: the level-load window of lp_an.py is the event window; this one is the coarse audio view."""
import re,sys
S=sys.argv[1]; tags=sys.argv[2:]
def load(tag):
    fps={};aud={};load_s=set();first_load=None
    for l in open(f"{S}/{tag}.log",errors="replace"):
        m=re.match(r"\s*([\d.]+) (.*)",l)
        if not m: continue
        s=int(float(m.group(1))); r=m.group(2)
        f=re.search(r"\[FPS\] fps=(\d+) draws=(\d+)",r)
        if f: fps[s]=(int(f.group(1)),int(f.group(2)))
        a=re.search(r"\[AUDIO\].*pico=([\d.]+).*espera=(\d+) pulados=(\d+) perdidos=(\d+) falta=(\d+)",r)
        if a: aud[s]=(float(a.group(1)),int(a.group(2)),int(a.group(3)),int(a.group(5)))
        if "open '/dev_bdvd/PS3_GAME/USRDIR/LoadingScreens/" in r and ".ls'" in r and s>10:
            load_s.update(range(s,s+4)); first_load=first_load or s
    return fps,aud,load_s
for tag in tags:
    fps,aud,ld=load(tag)
    cat={}
    for s in sorted(set(fps)&set(aud)):
        c="CARGA" if s in ld else ("GAMEPLAY" if fps[s][1]>=100 else ("TITULO" if fps[s][1]<10 else "OUTRO"))
        cat.setdefault(c,[]).append(s)
    print(f"== {tag}: {len(aud)} s de áudio; CARGA abriu em t={min(ld) if ld else None}")
    for c in ("TITULO","CARGA","OUTRO","GAMEPLAY"):
        ss=cat.get(c,[]);
        if not ss: print(f"  {c:9s} 0 s"); continue
        esp=sum(aud[s][1] for s in ss); pul=sum(aud[s][2] for s in ss); fal=sum(aud[s][3] for s in ss)
        seg=sum(1 for s in ss if aud[s][2]>0); fm=sum(fps[s][0] for s in ss)/len(ss); fmin=min(fps[s][0] for s in ss)
        pico=sum(aud[s][0] for s in ss)/len(ss)
        print(f"  {c:9s} {len(ss):3d} s  fps med={fm:4.1f} min={fmin:2d} | espera={esp:5d} pulados={pul:5d} ({100*pul/(188*len(ss)):.1f}% dos blocos) seg_c/pulo={seg:3d} falta={fal} pico_med={pico:.2f}")
    g=cat.get("GAMEPLAY",[]); print("  VALIDA" if len(g)>=60 and ld else f"  INVALIDA (gameplay={len(g)} s, carga={'sim' if ld else 'não'})")
