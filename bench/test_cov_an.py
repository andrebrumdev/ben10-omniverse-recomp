#!/usr/bin/env python3
"""Testes de cov_an.py (contagem dinamica de instrucoes SPU por linha a partir de cobertura lcov)."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cov_an

SRC = """/* Auto-generated */
void job_spu_func_00001000(spu_context* ctx) {
        ctx->gpr[2] = spu_ila(0x22280);
        { ctx->pc = 0x10E0; SPU_TAILCALL(job_spu_func_000010E0(ctx)); }
}

void job_spu_func_000012E0(spu_context* ctx) {
loc_000012E0:
        ctx->gpr[65] = spu_il(2);
        ctx->gpr[75] = spu_ls_read128(ctx, ctx->gpr[21]._u32[0] + 0x0);
        ctx->gpr[19] = spu_shufb(ctx->gpr[75], ctx->gpr[76], ctx->gpr[77]);
        /* nop */;
        ctx->gpr[20] = spu_fma(ctx->gpr[19], ctx->gpr[75], ctx->gpr[65]);
        if (ctx->gpr[18]._u32[0] == 0) goto loc_000012E0;
        spu_ls_write128(ctx, ctx->gpr[1]._u32[0] + 0x10, ctx->gpr[0]);
}
"""
# lines (1-based): 3 ila (1 time), 7 func 12E0 header, 9 il, 10 ld, 11 shufb, 12 nop, 13 fma, 14 branch, 15 st
LCOV = """SF:spu_recomp.c
DA:3,1
DA:9,1000
DA:10,1000
DA:11,1000
DA:13,1000
DA:14,1000
DA:15,4
end_of_record
"""

class CovAn(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        open(os.path.join(self.d, "spu_recomp.c"), "w").write(SRC)
        open(os.path.join(self.d, "c.lcov"), "w").write(LCOV)
    def test_per_function_histogram(self):
        r = cov_an.analyze(os.path.join(self.d, "spu_recomp.c"), os.path.join(self.d, "c.lcov"))
        f = r["funcs"]["job_spu_func_000012E0"]
        self.assertEqual(f["ops"]["spu_shufb"], 1000)
        self.assertEqual(f["ops"]["spu_fma"], 1000)
        self.assertEqual(f["ops"]["spu_il"], 1000)
        self.assertEqual(f["ops"]["spu_ls_write128"], 4)
        self.assertEqual(f["total"], 5004)           # il ld shufb fma branch = 5 x 1000, st = 4
    def test_nop_and_branch_lines(self):
        r = cov_an.analyze(os.path.join(self.d, "spu_recomp.c"), os.path.join(self.d, "c.lcov"))
        f = r["funcs"]["job_spu_func_000012E0"]
        self.assertEqual(f["ops"].get("branch"), 1000)  # the `if (...) goto` line is one SPU branch instruction
        self.assertNotIn("nop", f["ops"])               # `/* nop */;` has count 0 in lcov (no code) and is not an op
    def test_other_function_separated(self):
        r = cov_an.analyze(os.path.join(self.d, "spu_recomp.c"), os.path.join(self.d, "c.lcov"))
        self.assertEqual(r["funcs"]["job_spu_func_00001000"]["ops"], {"spu_ila": 1})
    def test_loop_iterations_is_first_line_after_label(self):
        r = cov_an.analyze(os.path.join(self.d, "spu_recomp.c"), os.path.join(self.d, "c.lcov"))
        self.assertEqual(r["funcs"]["job_spu_func_000012E0"]["first_count"], 1000)
    def test_class_shares(self):
        r = cov_an.analyze(os.path.join(self.d, "spu_recomp.c"), os.path.join(self.d, "c.lcov"))
        sh = cov_an.class_shares(r["funcs"]["job_spu_func_000012E0"]["ops"])
        tot = sum(sh.values())
        self.assertAlmostEqual(tot, 1.0, places=6)
        self.assertGreater(sh["shufb_rot"], 0.15)
        self.assertGreater(sh["float"], 0.15)
    def test_uncounted_line_is_zero(self):
        r = cov_an.analyze(os.path.join(self.d, "spu_recomp.c"), os.path.join(self.d, "c.lcov"))
        self.assertEqual(r["unmapped_lines"], 0)

class CovAnMultiSF(unittest.TestCase):
    def test_selects_record_by_source_file(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "spu_recomp.c"), "w") as fh: fh.write(SRC)
        with open(os.path.join(d, "m.lcov"), "w") as fh:
            fh.write("SF:/x/job_a/spu_recomp.c\nDA:9,7\nend_of_record\nSF:/x/job_b/spu_recomp.c\nDA:9,1000\nDA:10,1000\nend_of_record\n")
        r = cov_an.analyze(os.path.join(d, "spu_recomp.c"), os.path.join(d, "m.lcov"), sf="job_b/spu_recomp.c")
        self.assertEqual(r["funcs"]["job_spu_func_000012E0"]["ops"]["spu_il"], 1000)
        r = cov_an.analyze(os.path.join(d, "spu_recomp.c"), os.path.join(d, "m.lcov"), sf="job_a/spu_recomp.c")
        self.assertEqual(r["funcs"]["job_spu_func_000012E0"]["ops"]["spu_il"], 7)

if __name__ == "__main__":
    unittest.main()
