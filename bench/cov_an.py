#!/usr/bin/env python3
"""Contagem dinamica de instrucoes SPU por linha (plano ben10-jobcost, Tarefa 1).

Uma linha do spu_recomp.c liftado e' UMA instrucao SPU (`ctx->gpr[x] = spu_op(...)`, `if (...) goto`, ...), logo a contagem de
execucao por linha da cobertura (llvm-cov export -format=lcov) e' o histograma dinamico de instrucoes SPU.

uso: cov_an.py <spu_recomp.c> <cobertura.lcov> [--sf job_844e80/spu_recomp.c] [--func NOME] [--jobs N]
  imprime, por funcao liftada (ou so a pedida): total de instrucoes SPU executadas, execucoes da 1a linha do corpo
  (= iteracoes se a funcao e' um laco), histograma por helper e por classe (shufb/rot, float, mem LS, inteiro, branch).
  --jobs N: divide por N (numero de jobs na janela de contagem) para dar por job.
"""
import re, sys
from collections import Counter

FUNC_RE = re.compile(r"^void (\w+)\(spu_context\* ctx\) \{")
CALL_RE = re.compile(r"\b(spu_[a-z0-9_]+)\(")
GOTO_RE = re.compile(r"^\s*if \(.*\) goto \w+;")

def _lcov(path, sf=None):
    """line -> count; with `sf`, only the records whose SF: path ends with it (a merged lcov has one record per file)."""
    cnt = {}; cur = None
    with open(path, errors="replace") as fh: raw = fh.read().split("\n")
    for l in raw:
        l = l.strip()
        if l.startswith("SF:"): cur = l[3:]
        elif l.startswith("DA:") and (sf is None or (cur or "").endswith(sf)):
            n, c = l[3:].split(",")[:2]
            cnt[int(n)] = cnt.get(int(n), 0) + int(c)     # same line in several instantiations: sum
    return cnt

def analyze(src, lcov, sf=None):
    with open(src, errors="replace") as fh: lines = fh.read().split("\n")
    cnt = _lcov(lcov, sf)
    funcs = {}; cur = None
    for i, l in enumerate(lines, 1):
        m = FUNC_RE.match(l)
        if m:
            cur = m.group(1); funcs[cur] = {"ops": Counter(), "total": 0, "first_count": None, "lines": (i, i)}
            continue
        if cur is None: continue
        if l.startswith("}"):
            funcs[cur]["lines"] = (funcs[cur]["lines"][0], i); cur = None; continue
        if re.match(r"^loc_[0-9A-Fa-f]+:", l): continue
        c = cnt.get(i, 0)
        if funcs[cur]["first_count"] is None and i in cnt:      # first executable line of the body (= iterations for a loop at the entry)
            funcs[cur]["first_count"] = c
        if c <= 0: continue
        if GOTO_RE.match(l): names = ["branch"]
        else:
            names = CALL_RE.findall(l)
            if not names and "SPU_TAILCALL" in l: names = ["tailcall"]
        for n in names:
            funcs[cur]["ops"][n] += c; funcs[cur]["total"] += c
    unmapped = 0
    for n, c in cnt.items():
        if c > 0 and not any(f["lines"][0] <= n <= f["lines"][1] for f in funcs.values()): unmapped += 1
    for f in funcs.values():
        f["ops"] = dict(f["ops"])
        if f["first_count"] is None: f["first_count"] = 0
    return {"funcs": funcs, "unmapped_lines": unmapped}

_SHUF = ("spu_shufb", "spu_rotqby", "spu_rotqbyi", "spu_rotqbi", "spu_rotqbii", "spu_shlqby", "spu_shlqbyi", "spu_shlqbi", "spu_shlqbii",
         "spu_rotqmby", "spu_rotqmbyi", "spu_rotqmbi", "spu_rotqmbii", "spu_rotqbybi", "spu_shlqbybi", "spu_rotqmbybi")
_FLOAT = ("spu_fa", "spu_fs", "spu_fm", "spu_fma", "spu_fms", "spu_fnms", "spu_fcgt", "spu_fceq", "spu_fcmgt", "spu_fcmeq", "spu_csflt",
          "spu_cflts", "spu_cuflt", "spu_cfltu", "spu_frest", "spu_frsqest", "spu_fi", "spu_fesd", "spu_frds")
def op_class(n):
    if n in _SHUF: return "shufb_rot"
    if n in _FLOAT: return "float"
    if n in ("spu_ls_read128", "spu_ls_write128"): return "mem"
    if n in ("branch", "tailcall"): return "branch"
    return "int_other"

def class_shares(ops):
    t = sum(ops.values()) or 1
    out = Counter()
    for n, c in ops.items(): out[op_class(n)] += c / t
    for k in ("shufb_rot", "float", "mem", "int_other", "branch"): out.setdefault(k, 0.0)
    return dict(out)

def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    func = None; jobs = 1.0; sf = None
    if "--sf" in argv: sf = argv[argv.index("--sf") + 1]; args.remove(sf)
    if "--func" in argv: func = argv[argv.index("--func") + 1]; args.remove(func)
    if "--jobs" in argv: jobs = float(argv[argv.index("--jobs") + 1]); args.remove(argv[argv.index("--jobs") + 1])
    r = analyze(args[0], args[1], sf)
    gt = sum(f["total"] for f in r["funcs"].values())
    print(f"total SPU instructions executed (all functions): {gt:.0f} ({gt/jobs:.0f}/job) unmapped_lines={r['unmapped_lines']}")
    for n, f in sorted(r["funcs"].items(), key=lambda kv: -kv[1]["total"]):
        if func and func not in n: continue
        if f["total"] == 0: continue
        print(f"{n}: total={f['total']:.0f} ({f['total']/jobs:.0f}/job, {100*f['total']/gt:.1f}% of all) first_count={f['first_count']} ({f['first_count']/jobs:.1f}/job)")
        for k, v in sorted(class_shares(f["ops"]).items(), key=lambda kv: -kv[1]): print(f"   class {k:10s} {100*v:5.1f}%")
        for k, v in sorted(f["ops"].items(), key=lambda kv: -kv[1])[:40]: print(f"   {k:18s} {v:12.0f} {100*v/f['total']:5.1f}%")

if __name__ == "__main__":
    main(sys.argv[1:])
