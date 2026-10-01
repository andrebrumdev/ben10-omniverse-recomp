#!/usr/bin/env python3
"""Tabela por braco do A/B de PS3_JC_WORKERS (plano 60 fps, Tarefa 5), em cima do t5_an.py.

uso: t5_table.py <dir> [--exclude tagA,tagB]     agrupa lp_n<N><rep>.log por N (tag = n + digito de N + letra da repeticao)

Por braco: media entre corridas [min-max] de cada metrica; por corrida: uma linha. Pior/melhor corrida nunca escolhidas:
quando as corridas de um braco discordam > 10% em fps, a coluna `agree` diz NAO e o braco precisa de mais uma corrida.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t5_an  # noqa: E402

COLS = [("fps_avg", "fps avg"), ("ft_p50", "p50 ms"), ("ft_p95", "p95 ms"), ("ft_p99", "p99 ms"),
        ("us_job_844e80", "us/job 844e80"), ("chain_ms_f", "chain ms/f"), ("serial_ms_f", "job-sum ms/f"),
        ("hold_ms_f", "giant hold ms/f"), ("decode_ms_f", "decode ms/f"), ("gpu_ms", "gpu ms"),
        ("skip_pct", "audio skip %"), ("speed", "speed"), ("pcore_med", "P-core")]


def fmt(v):
    return ("%.2f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def main(d, exclude):
    tags = sorted(re.match(r".*/lp_(n\d[a-z])\.log$", p).group(1) for p in glob.glob(os.path.join(d, "lp_n[0-9][a-z].log")))
    runs = {t: t5_an.an(d, t) for t in tags}
    arms = {}
    for t, r in runs.items():
        if t in exclude or not r.get("valid"):
            continue
        arms.setdefault(int(t[1]), []).append(r)
    print("| N | runs | " + " | ".join(c[1] for c in COLS) + " | agree |")
    print("|---|---|" + "---|" * (len(COLS) + 1))
    for n in sorted(arms):
        rs = arms[n]
        cells = []
        for k, _ in COLS:
            vs = [r[k] for r in rs if k in r]
            cells.append("%s [%s-%s]" % (fmt(round(sum(vs) / len(vs), 2)), fmt(min(vs)), fmt(max(vs))) if vs else "-")
        f = [r["fps_avg"] for r in rs]
        agree = "sim" if max(f) <= 1.10 * min(f) else "NAO (%.0f%%)" % (100.0 * (max(f) / min(f) - 1))
        print("| %d | %s | %s | %s |" % (n, ",".join(r["tag"] for r in rs), " | ".join(cells), agree))
    print()
    print("| run | fps avg | p50 | p95 | p99 | us/job | chain/f | job-sum/f | hold/f | decode/f | skip % | falta | speed | mode1 % | P-core med/min | "
          "load(med) | outside>100% (ps/top) | swap MB |")
    print("|---|" + "---|" * 17)
    for t, r in runs.items():
        print("| %s%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s/%s | %s | %s | %s |" % (
            t, " (excl.)" if t in exclude else "", r.get("fps_avg"), r.get("ft_p50"), r.get("ft_p95"), r.get("ft_p99"),
            r.get("us_job_844e80"), r.get("chain_ms_f"), r.get("serial_ms_f"), r.get("hold_ms_f"), r.get("decode_ms_f"),
            r.get("skip_pct"), r.get("falta"), r.get("speed"), r.get("mode1_pct"), r.get("pcore_med"), r.get("pcore_min"),
            r.get("reg_load1_med"), r.get("reg_gt100"), r.get("reg_swap_mb")))


if __name__ == "__main__":
    ex = set()
    if "--exclude" in sys.argv:
        i = sys.argv.index("--exclude")
        ex = set(sys.argv[i + 1].split(","))
    main(sys.argv[1], ex)
