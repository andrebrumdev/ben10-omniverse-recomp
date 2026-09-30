#!/usr/bin/env python3
"""CPU-by-thread view of the level-load window (needs <dir>/lp_<tag>.thr from thrmon).
usage: lp_an2.py <dir> <tag>...   -> load window, ppu:veThread8 CPU, process CPU, SPURS workers CPU."""
import re,sys
def main(P,tags):
  for tag in tags:
      t0=None; L=None; E=None; lastopen=None
      fl=[]
      for l in open(f"{P}/lp_{tag}.log",errors="replace"):
          if l.startswith("T0 "): t0=float(l.split()[1]); continue
          m=re.match(r"\s*([\d.]+) (.*)",l)
          if not m: continue
          t=float(m.group(1)); r=m.group(2)
          if L is None and t>55 and "LoadingScreens/" in r and ".ls'" in r: L=t
          if L and E is None:
              f=re.search(r"\[FPS\] fps=(\d+) draws=(\d+)",r)
              if f and t>L+1 and int(f.group(2))>=100: E=t
              if "[fs] open" in r: lastopen=t
      v8=0; tot=0; spw=0; rows=0
      for l in open(f"{P}/lp_{tag}.thr"):
          p=l.split(" ",1); t=float(p[0])-t0
          if L-1<=t<=E+0.5:
              rows+=1
              m=re.search(r"ppu:veThread8 x1=(\d+)",p[1]); v8+=int(m.group(1)) if m else 0
              m=re.search(r"tot_ms=(\d+)",p[1]); tot+=int(m.group(1))
              m=re.search(r"host:spurs-worker x5=(\d+)",p[1]); spw+=int(m.group(1)) if m else 0
      print(f"{tag:4s} L={L:.1f} E={E:.1f} load={E-L:.1f}s last_open=+{lastopen-L:.1f}s veThread8_cpu={v8/1000:.2f}s proc_cpu={tot/1000:.2f}s spurs={spw/1000:.2f}s over {rows} rows")

if __name__=="__main__":
  main(sys.argv[1],sys.argv[2:])
