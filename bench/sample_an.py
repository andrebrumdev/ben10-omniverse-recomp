#!/usr/bin/env python3
"""Tarefa 6 (plano 60 fps): onde o tempo das threads do job chain vai, a partir de um `sample <pid>` (bench/run_lp.sh gs).

uso: sample_an.py <arquivo.sampleG.txt>...

Le o grafo de chamadas do `sample`, pega as threads que passam por jc_worker/jc_do_job/jc_execute, calcula o tempo PROPRIO de cada no
(contagem do no menos a soma dos filhos diretos) e agrupa por categoria: corpo do job (funcoes liftadas ben10_job_*), mem* da libc (memset do
contexto, copias do binario/DMA), espera no kernel (psynch/semwait: ocioso), mutex da linha de reserva, canais/MFC, cola do job chain, e o
overhead das proprias sondas (thread_selfcounts, mach_absolute_time). Imprime tambem as funcoes de topo.
O `sample` perturba o jogo (fps cai): so a FATIA vale, nunca fps/ms de uma corrida amostrada.
"""
import collections
import re
import sys


def parse(path):
    lines = open(path, errors="replace").read().split("\n")
    start = next(k for k, l in enumerate(lines) if l.startswith("Call graph:")) + 1
    threads, cur = [], None
    for l in lines[start:]:
        if l.startswith("Total number in stack") or l.startswith("Sort by top of stack"):
            break
        m = re.match(r"^(\s+)(\d+) (Thread_\d+.*)$", l)
        if m and len(m.group(1)) == 4:
            cur = {"hdr": m.group(3), "n": int(m.group(2)), "nodes": []}
            threads.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^([ +!:|]*?)(\d+) (.*)$", l)
        if not m:
            continue
        name = re.sub(r"\s+\(in .*$", "", m.group(3)).strip()
        name = re.sub(r"\s+\+ \d+.*$", "", name)
        cur["nodes"].append((len(m.group(1)), int(m.group(2)), name))
    return threads


def selfs(th):
    """Tempo proprio por funcao: no pre-ordem com pilha de (profundidade, contagem, soma dos filhos)."""
    res = collections.Counter()
    stack = []                                   # [depth, count, name, children_sum]

    def pop_to(depth):
        while stack and stack[-1][0] >= depth:
            d, n, name, ch = stack.pop()
            res[name] += max(0, n - ch)
            if stack:
                stack[-1][3] += n
    for depth, n, name in th["nodes"]:
        pop_to(depth)
        stack.append([depth, n, name, 0])
    pop_to(-1)
    return res


CATS = (
    ("job-body (lifted ben10_job_*)", lambda k: k.startswith("ben10_job")),
    ("libc mem* (memset/memmove)", lambda k: any(x in k for x in ("memmove", "memcpy", "memset", "bzero"))),
    ("wait/sync (kernel)", lambda k: any(x in k for x in ("psynch", "semwait", "kevent", "mach_msg", "ulock", "cond"))),
    ("atomic-line lock", lambda k: "ps3_atomic_line" in k),
    ("channel/MFC", lambda k: "spu_wrch" in k or "spu_rdch" in k or "mfc" in k.lower()),
    ("probe overhead (selfcounts/clocks)", lambda k: any(x in k for x in ("thread_selfcounts", "thread_selfusage", "mach_absolute_time", "clock_gettime", "mach_timebase"))),
    ("signals (sigsetjmp path)", lambda k: any(x in k for x in ("sigprocmask", "sigaltstack"))),
    ("jobchain glue", lambda k: k.startswith(("jc_", "spu_workload", "spu_context"))),
)


def report(path):
    th = parse(path)
    work = [t for t in th if any(("jc_worker" in x[2] or "jc_do_job" in x[2] or "jc_execute" in x[2]) for x in t["nodes"])]
    print("%s: %d threads, %d with the job chain" % (path, len(th), len(work)))
    tot, n_all = collections.Counter(), 0
    for t in work:
        s = selfs(t)
        tot.update(s)
        n_all += t["n"]
    cat = collections.Counter()
    for k, v in tot.items():
        for name, pred in CATS:
            if pred(k):
                cat[name] += v
                break
        else:
            cat["other"] += v
    idle = cat["wait/sync (kernel)"]
    busy = n_all - idle
    print("  samples (jc threads) %d, of which waiting in the kernel %d (%.1f%%), busy %d" % (n_all, idle, 100.0 * idle / max(1, n_all), busy))
    for name, v in cat.most_common():
        if name == "wait/sync (kernel)":
            continue
        print("  %5.1f%% of busy  %6d  %s" % (100.0 * v / max(1, busy), v, name))
    print("  top self functions:", ", ".join("%s:%d" % kv for kv in tot.most_common(8)))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        report(p)
