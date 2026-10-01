#!/usr/bin/env python3
"""Teste do sample_an.py com um `sample` sintetico: tempo proprio (no menos filhos), categorias e a fatia de espera."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sample_an  # noqa: E402

SAMPLE = """Analysis of sampling boot_ben10 (pid 1) every 1 millisecond
Call graph:
    100 Thread_1: Main Thread   DispatchQueue_<multiple>
    + 100 main  (in boot_ben10) + 1  [0x1]
    80 Thread_2
    + 80 jc_worker  (in boot_ben10) + 804  [0x2]
    +   50 jc_do_job  (in boot_ben10) + 10  [0x3]
    +   ! 40 ben10_job_844e80_spu_func_000012E0  (in boot_ben10) + 1744,588,...  [0x4,0x5,...]
    +   ! 6 _platform_memmove  (in libsystem_platform.dylib) + 1  [0x6]
    +   ! 4 __bzero  (in libsystem_platform.dylib) + 2  [0x7]
    +   30 __psynch_cvwait  (in libsystem_kernel.dylib) + 8  [0x8]

Total number in stack (recursive counted multiple, when >= 5):
"""


def main():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(SAMPLE)
        path = f.name
    try:
        th = sample_an.parse(path)
        assert len(th) == 2, th
        work = [t for t in th if any("jc_worker" in x[2] for x in t["nodes"])]
        assert len(work) == 1 and work[0]["n"] == 80
        s = sample_an.selfs(work[0])
        assert s["ben10_job_844e80_spu_func_000012E0"] == 40, s
        assert s["jc_do_job"] == 0, s                      # 50 - (40 + 6 + 4): o no pai nao conta o que e' dos filhos
        assert s["_platform_memmove"] == 6 and s["__bzero"] == 4 and s["__psynch_cvwait"] == 30
        assert s["jc_worker"] == 0
        out = []
        old = sys.stdout

        class W:
            def write(self, x): out.append(x)
            def flush(self): pass
        sys.stdout = W()
        try:
            sample_an.report(path)
        finally:
            sys.stdout = old
        txt = "".join(out)
        assert "waiting in the kernel 30 (37.5%), busy 50" in txt, txt
        assert "80.0% of busy      40  job-body" in txt, txt
        assert "20.0% of busy      10  libc mem*" in txt, txt
    finally:
        os.unlink(path)
    print("ok")


if __name__ == "__main__":
    main()
