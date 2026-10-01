#!/usr/bin/env python3
"""Auditoria dos consumidores do passo de quadro do Ben 10 (BLUS31017) -- diagnostico, nunca toca o lift original.

O jogo guarda o passo da logica em ticks de 1/600 s: inteiro em [0x90177C] (mode em [0x901778]) e o double
em 0x8B4270 (periodo do limitador). Ver notes/2026-10-xx-framestep-audit.md.

  python3 tools/audit_framestep.py scan <lift>                  -> lista estatica dos sitios (stdout)
  python3 tools/audit_framestep.py instrument <lift> <out_lift> -> copia de rascunho do lift com contadores por sitio
  python3 tools/audit_framestep.py analyze <log> --map <out_lift>_sites.txt
  python3 tools/audit_framestep.py census <lift> <out_lift>     -> censo DINAMICO por endereco efetivo (sem lista estatica)
  python3 tools/audit_framestep.py analyze-census <log>

`instrument` chama tools/probe_ticklog.py (linhas [TICKLOG]/[FRMODE]) e acrescenta, tudo atras de env, OFF por padrao:
  PS3_EXP_TICKLOG=1          liga as linhas [S9X] (uma por quadro: ticks, lr de B5C4C, lr do limitador, [0x90177C], deltas por sitio),
                             [S9XSUM] e [S9XARG] a cada 10 s
  PS3_S9X_FLIP_AT_S=<s>      escreve UMA vez o inteiro [0x90177C]=PS3_S9X_FLIP_VAL (padrao 10) aos <s> s do primeiro quadro
                             (o double e o mode ficam intactos): experimento de "cache de entrada" da malha de cena
Build e corrida (nunca sobre o recomp_macos):
  OUT=$PWD/boot_ben10_s9x ./build_macos.sh <out_lift>
  LOCK_DIR=... BIN=boot_ben10_s9x bench/run_lp.sh <tag> clean PS3_EXP_TICKLOG=1
Limites do metodo (declarados, nao escondidos):
  * `scan` rastreia o registrador-base DENTRO da mesma funcao do lift; um clone de fragmento que recebe a base de outro
    fragmento escapa (achado: func_000F7EE0 em _005, leitura do double, listado em EXTRA e nao instrumentado).
  * leituras indexadas `(rA+rB)` sobre bases proximas ficam como INDEXED? (nao classificadas).
"""
import collections, glob, os, re, subprocess, sys

# ---- fatos do EBOOT BLUS31017 (verificados no ELF: TOC=0x8B5C30) -------------------------------------------------
SLOTS = {-0x7B94: 0x901400, -0x58A0: 0x90177C, -0x72B0: 0x901780, -0x59E8: 0x901780, -0x532C: 0x901770,
         -0x6C28: 0x901410, -0x30E8: 0x901410, -0x7B50: 0x8B4260, -0x4E34: 0x8B4260}
TARGETS = {0x90177C: 'STEP', 0x901778: 'MODE', 0x8B4270: 'DBL'}
FN_RE = re.compile(r'^void (func_[0-9A-F]+)\(ppu_context\* ctx\)')
LD_RE = re.compile(r'ctx->gpr\[(\d+)\] = vm_read32\(ctx->gpr\[2\] \+ -0x([0-9A-F]+)\);')
ASG_RE = re.compile(r'^\s*ctx->gpr\[(\d+)\] = (.*);')
ACC_RE = re.compile(r'(vm_read(?:8|16|32|64)|vm_write(?:8|16|32|64))\(ctx->gpr\[(\d+)\] \+ (-?0x[0-9A-F]+|\d+)')
ACCX_RE = re.compile(r'(vm_read(?:8|16|32|64)|vm_write(?:8|16|32|64))\(\(ctx->gpr\[(\d+)\] \+ ctx->gpr\[(\d+)\]\)')
ACCESSORS = ['func_00091E64', 'func_00091E78', 'func_00091E90', 'func_00091EA4', 'func_00091EBC', 'func_00091ED0',
             'func_00091EE8', 'func_00091F00', 'func_00091F14', 'func_00091F2C', 'func_00091F40', 'func_00091F54',
             'func_00091F6C', 'func_0008C948']
ENTRY_HIST = [('func_0051F860', 83), ('func_0051B928', 84)]   # histograma do r4 (dt recebido) na entrada
INC = os.path.dirname(os.path.abspath(__file__))


def _int(s):
    return int(s, 16 if '0x' in s else 10)


def scan(lift):
    """-> (sites, extra): sites = [(file, line, func, kind, op, base-slot, slot-load-line)]"""
    out, extra = [], []
    for f in sorted(glob.glob(os.path.join(lift, 'ppu_recomp_*.cpp'))):
        lines = open(f, errors='ignore').read().split('\n')
        cur, track = None, {}
        for i, l in enumerate(lines, 1):
            m = FN_RE.match(l)
            if m:
                cur, track = m.group(1), {}
                continue
            if cur is None:
                continue
            m = LD_RE.search(l)
            if m and -int(m.group(2), 16) in SLOTS:
                track[int(m.group(1))] = (SLOTS[-int(m.group(2), 16)], 'slot-%s' % m.group(2), i)
                continue
            for a in ACC_RE.finditer(l):
                op, r, off = a.group(1), int(a.group(2)), _int(a.group(3))
                if r in track and track[r][0] + off in TARGETS:
                    out.append((os.path.basename(f), i, cur, TARGETS[track[r][0] + off], op, track[r][1], track[r][2]))
            for a in ACCX_RE.finditer(l):
                r1, r2 = int(a.group(2)), int(a.group(3))
                if r1 in track or r2 in track:
                    out.append((os.path.basename(f), i, cur, 'INDEXED?', a.group(1), str(track.get(r1) or track.get(r2)), 0))
            m = ASG_RE.match(l)
            if m:
                d, rhs = int(m.group(1)), m.group(2)
                m1 = re.fullmatch(r'ppc_rldicl\(ctx->gpr\[(\d+)\], 0, 32\)', rhs)
                m2 = re.fullmatch(r'ctx->gpr\[(\d+)\] \| ctx->gpr\[(\d+)\]', rhs)
                m3 = re.fullmatch(r'ctx->gpr\[(\d+)\] \+ \(int64_t\)\((-?0x[0-9A-F]+|-?\d+)\)', rhs)
                src, delta = None, 0
                if m1:
                    src = int(m1.group(1))
                elif m2 and m2.group(1) == m2.group(2):
                    src = int(m2.group(1))
                elif m3:
                    src, delta = int(m3.group(1)), _int(m3.group(2))
                if src is not None and src in track:
                    track[d] = (track[src][0] + delta, track[src][1] + ('+%#x' % delta if delta else ''), track[src][2])
                    if track[d][0] in TARGETS:
                        out.append((os.path.basename(f), i, cur, TARGETS[track[d][0]], 'ADDR-TAKEN', track[d][1], track[src][2]))
                else:
                    track.pop(d, None)
            if re.search(r'func_[0-9A-F]+\(ctx\)|DRAIN_TRAMPOLINE', l):
                for r in [r for r in track if 3 <= r <= 12]:
                    track.pop(r)
        # segunda passada textual: clones do calculo "ticks = (int)(double * 600.0f)" / "alvo_us = double * 1e6f" que
        # recebem a base de outro fragmento (o rastreio acima nao os ve)
        cur = None
        for i, l in enumerate(lines):
            m = FN_RE.match(l)
            if m:
                cur = m.group(1)
            if re.search(r'vm_read64\(ctx->gpr\[\d+\] \+ 0x10\)', l):
                win = ' '.join(lines[i:i + 6])
                if '-0x7B28)' in win or '-0x75AC)' in win:
                    extra.append((os.path.basename(f), i + 1, cur, 'DBL', 'clone-textual'))
    return out, extra


def cmd_scan(lift):
    sites, extra = scan(lift)
    for s in sites:
        print(*s)
    for e in extra:
        print('#EXTRA', *e)


def build_sites(lift):
    sites, _ = scan(lift)
    keep = sorted(set((f, n, fn, k, op) for f, n, fn, k, op, _b, _l in sites if k != 'INDEXED?'))
    return keep


def cmd_instrument(lift, dst):
    lift, dst = os.path.abspath(lift), os.path.abspath(dst)
    src2 = dst + '.src'
    sites = build_sites(lift)
    byfile = collections.defaultdict(dict)
    with open(os.path.join(os.path.dirname(dst), os.path.basename(dst) + '_sites.txt'), 'w') as m:
        for i, (f, n, fn, k, op) in enumerate(sites):
            byfile[f][n] = i
            m.write('%d %s:%d %s %s %s\n' % (i, f, n, fn, k, op))
        for fn, i in ENTRY_HIST:
            m.write('%d ENTRY-HIST:%s %s r4 -\n' % (i, fn, fn))
    os.makedirs(src2, exist_ok=True)
    touched = set(byfile)
    for name in os.listdir(lift):
        d, s = os.path.join(src2, name), os.path.join(lift, name)
        if os.path.lexists(d):
            continue
        base = name.split('.cpp')[0] + '.cpp' if '.cpp' in name else name
        if (base in touched and name != base) or name in touched:
            continue                                   # objetos dos chunks tocados nao se reaproveitam
        if name.startswith(('ppu_recomp', 'ppu_stubs')) or name == 'spu_jobs':
            os.symlink(s, d)
    decl = 'extern "C" void s9x_hit(int, uint64_t);'
    for f, lines in byfile.items():
        src = open(os.path.join(lift, f), errors='surrogateescape').read().split('\n')
        for n, i in lines.items():
            assert 'vm_read' in src[n - 1] or 'vm_write' in src[n - 1], (f, n, src[n - 1])
            src[n - 1] = '{ s9x_hit(%d, ctx->thread_id); } ' % i + src[n - 1]
        assert src[1].startswith('#include "ppu_recomp.h"')
        src.insert(2, decl)
        open(os.path.join(src2, f), 'w', errors='surrogateescape').write('\n'.join(src))
    subprocess.check_call([sys.executable, os.path.join(INC, 'probe_ticklog.py'), src2, dst])
    # ---- chunk 000: frame hook, accessor args, limiter lr, flip, runtime
    p = os.path.join(dst, 'ppu_recomp_000.cpp')
    c = open(p, errors='surrogateescape').read()
    a = '{ static int s_on = -1; static uint64_t s_calls, s_sum, s_t0;'
    assert c.count(a) == 1
    c = c.replace(a, 's9x_frame((uint32_t)ctx->gpr[3], ctx->thread_id, (uint32_t)ctx->lr);\n        ' + a, 1)
    names = {(f, n): i for f, ls in byfile.items() for n, i in ls.items()}
    acc_idx = [i for (f, n, fn, k, op), i in zip(sites, range(len(sites))) if fn in ACCESSORS]
    for i in acc_idx:
        old = '{ s9x_hit(%d, ctx->thread_id); }' % i
        assert c.count(old) == 1, (i, c.count(old))
        c = c.replace(old, '{ s9x_hit2(%d, ctx->thread_id, (uint32_t)ctx->gpr[4]); }' % i)
    a = 'void func_000F7CF4(ppu_context* ctx) {\n'
    assert c.count(a) == 1
    c = c.replace(a, a + '        s9x_lim_lr = (uint32_t)ctx->lr;\n', 1)
    c = c.replace('extern "C" void s9x_hit(int, uint64_t);',
                  'extern "C" uint32_t s9x_lim_lr; extern "C" void s9x_hit(int, uint64_t); extern "C" void s9x_hit2(int, uint64_t, uint32_t);'
                  ' extern "C" void s9x_frame(uint32_t, uint64_t, uint32_t);', 1)
    c += RUNTIME
    open(p, 'w', errors='surrogateescape').write(c)
    # ---- chunk 001: histograma do dt (r4) recebido nas funcoes de atualizacao
    p1 = os.path.realpath(os.path.join(dst, 'ppu_recomp_001.cpp'))
    c = open(p1, errors='surrogateescape').read()
    for fn, i in ENTRY_HIST:
        a = 'void %s(ppu_context* ctx) {\n' % fn
        assert c.count(a) == 1, fn
        c = c.replace(a, a + '        s9x_hit2(%d, ctx->thread_id, (uint32_t)ctx->gpr[4]);\n' % i, 1)
    c = c.replace('extern "C" void s9x_hit(int, uint64_t);',
                  'extern "C" void s9x_hit(int, uint64_t); extern "C" void s9x_hit2(int, uint64_t, uint32_t);', 1)
    open(p1, 'w', errors='surrogateescape').write(c)
    print('ok', dst, 'sites', len(sites), '(+%d entry-hist)' % len(ENTRY_HIST))


RUNTIME = r'''
/* ---- scratch audit runtime (fps60x, task 1): per-site read counters for [0x90177C]/[0x901778]/double 0x8B4270 ---- */
extern "C" {
static uint32_t s9x_cnt[128], s9x_prev[128], s9x_max[128];
static uint64_t s9x_tot[128], s9x_fw[128], s9x_tid[128];
void s9x_hit(int i, uint64_t tid) {
    __atomic_fetch_add(&s9x_cnt[i], 1u, __ATOMIC_RELAXED);
    __atomic_fetch_or(&s9x_tid[i], 1ull << (tid & 63), __ATOMIC_RELAXED);
}
uint32_t s9x_lim_lr;
static uint32_t s9x_av[128][16], s9x_ac[128][16];
void s9x_hit2(int i, uint64_t tid, uint32_t v) {
    s9x_hit(i, tid);
    for (int k = 0; k < 16; k++) {
        if (__atomic_load_n(&s9x_ac[i][k], __ATOMIC_RELAXED) && s9x_av[i][k] == v) { __atomic_fetch_add(&s9x_ac[i][k], 1u, __ATOMIC_RELAXED); return; }
        if (!__atomic_load_n(&s9x_ac[i][k], __ATOMIC_RELAXED)) { s9x_av[i][k] = v; __atomic_store_n(&s9x_ac[i][k], 1u, __ATOMIC_RELAXED); return; }
    }
}
void s9x_frame(uint32_t ticks, uint64_t tid, uint32_t lr) {
    static int on = -1; static uint64_t fr, t0, tl;
    if (on < 0) on = getenv("PS3_EXP_TICKLOG") ? 1 : 0;
    if (!on) return;
    struct timespec ts_; clock_gettime(CLOCK_MONOTONIC, &ts_);
    uint64_t now = (uint64_t)ts_.tv_sec * 1000000000ull + (uint64_t)ts_.tv_nsec;
    if (!t0) { t0 = now; tl = now; }
    fr++;
    { static double flip_at = -2; static int flip_done;
      if (flip_at == -2) { const char* e = getenv("PS3_S9X_FLIP_AT_S"); flip_at = e ? atof(e) : -1; }
      if (flip_at > 0 && !flip_done && (double)(now - t0) / 1e9 >= flip_at) {
          const char* v = getenv("PS3_S9X_FLIP_VAL"); uint32_t nv = v ? (uint32_t)atoi(v) : 10u;
          flip_done = 1; fprintf(stderr, "[S9XFLIP] t=%.3f [0x90177C] %u -> %u (integer only; double/mode untouched)\n", (double)(now - t0) / 1e9, (unsigned)vm_read32(0x90177C), nv);
          vm_write32(0x90177C, nv); } }
    char buf[2048]; int n = snprintf(buf, sizeof buf, "[S9X] f=%llu t=%.3f ticks=%u lr=0x%X limlr=0x%X g=%u tid=%llu d:", (unsigned long long)fr, (double)(now - t0) / 1e9, ticks, lr, s9x_lim_lr, (unsigned)vm_read32(0x90177C), (unsigned long long)tid);
    for (int i = 0; i < 128; i++) {
        uint32_t c = __atomic_load_n(&s9x_cnt[i], __ATOMIC_RELAXED); uint32_t d = c - s9x_prev[i];
        if (d) { s9x_prev[i] = c; s9x_tot[i] += d; s9x_fw[i]++; if (d > s9x_max[i]) s9x_max[i] = d;
                 if (n < (int)sizeof buf - 24) n += snprintf(buf + n, sizeof buf - n, " %d:%u", i, d); }
    }
    fprintf(stderr, "%s\n", buf);
    if (now - tl >= 10000000000ull) {
        tl = now; fprintf(stderr, "[S9XSUM] f=%llu t=%.1f", (unsigned long long)fr, (double)(now - t0) / 1e9);
        for (int i = 0; i < 128; i++) if (s9x_tot[i]) fprintf(stderr, " %d:%llu/%llu/%u/0x%llx", i, (unsigned long long)s9x_tot[i], (unsigned long long)s9x_fw[i], s9x_max[i], (unsigned long long)s9x_tid[i]);
        fprintf(stderr, "\n");
        for (int i = 0; i < 128; i++) { int any = 0; for (int k = 0; k < 16; k++) if (s9x_ac[i][k]) any = 1;
            if (any) { fprintf(stderr, "[S9XARG] %d:", i); for (int k = 0; k < 16; k++) if (s9x_ac[i][k]) fprintf(stderr, " %d/0x%X(x%u)", (int)s9x_av[i][k], s9x_av[i][k], s9x_ac[i][k]); fprintf(stderr, "\n"); } }
    }
}
}
'''


def cmd_analyze(log, mapf):
    sites = {}
    for l in open(mapf):
        p = l.split()
        sites[int(p[0])] = (p[1], p[2], p[3])
    ls, frames, frm, args = [], [], [], {}
    pre = re.compile(r'^\s*([0-9.]+) (.*)$')
    flips = []
    for raw in open(log, errors='replace'):
        m = pre.match(raw)
        if not m:
            continue
        t, s = float(m.group(1)), m.group(2)
        if 'LoadingScreens/' in s and ".ls'" in s and '/eng/' not in s:
            ls.append(t)
        mm = re.match(r'\[S9X\] f=(\d+) t=([0-9.]+) ticks=(\d+) lr=0x([0-9A-F]+)(?: limlr=0x([0-9A-F]+) g=(\d+))? tid=(\d+) d:(.*)', s)
        if mm:
            d = {}
            for kv in mm.group(8).split():
                a, b = kv.split(':')
                d[int(a)] = int(b)
            frames.append((t, float(mm.group(2)), int(mm.group(3)), int(mm.group(4), 16), int(mm.group(5) or '0', 16),
                           int(mm.group(6) or '0'), d))
        elif s.startswith('[FRMODE]'):
            frm.append((t, s.strip()))
        elif s.startswith('[S9XFLIP]'):
            flips.append((t, s.strip()))
        elif s.startswith('[S9XARG]'):
            a = re.match(r'\[S9XARG\] (\d+):(.*)', s)
            args[int(a.group(1))] = (t, a.group(2).strip())
    lvl = [x for x in ls if x > 55]
    t_lvl = lvl[0] if lvl else None

    def phase(t):
        if t_lvl is not None and t >= t_lvl + 20:
            return 'G'      # gameplay = .ls do nivel + 20 s -> fim
        if t_lvl is not None and t >= t_lvl:
            return 'L'      # carga do nivel
        if len(ls) >= 2 and t >= ls[1]:
            return 'B'      # titulo/menus
        return 'A'          # boot/intro
    ph = collections.defaultdict(list)
    for fr in frames:
        ph[phase(fr[0])].append(fr)
    print('log', log, 'frames', len(frames), '.ls opens (t):', ls)
    print('phase frames:', {k: len(v) for k, v in ph.items()})
    for k in 'ABLG':
        v = ph.get(k, [])
        print(k, 'ticks', dict(collections.Counter(x[2] for x in v)),
              'B5C4C lr', {hex(a): b for a, b in collections.Counter(x[3] for x in v).items()},
              'limiter lr', {hex(a): b for a, b in collections.Counter(x[4] for x in v).items()},
              'g', dict(collections.Counter(x[5] for x in v)))
    for t, s in frm[:40]:
        print('  ', t, s)
    for t, s in flips:
        print('  ', t, s)
    print('%-3s %-22s %-14s %-6s | reads/frames-with/max (pct of frames) per phase A B L G' % ('idx', 'site', 'func', 'kind'))
    for i in sorted(sites):
        row, tot = [], 0
        for k in 'ABLG':
            v = ph.get(k, [])
            r = sum(f[6].get(i, 0) for f in v)
            fw = sum(1 for f in v if f[6].get(i, 0))
            mx = max([f[6].get(i, 0) for f in v] or [0])
            tot += r
            row.append('%d/%d/%d (%d%%)' % (r, fw, mx, (100 * fw // len(v)) if v else 0))
        if tot:
            print('%-3d %-22s %-14s %-6s | %s' % (i, sites[i][0].replace('ppu_recomp_', ''), sites[i][1], sites[i][2], ' | '.join(row)))
    print('never hit:', [(i, sites[i][1]) for i in sorted(sites) if not any(f[6].get(i) for f in frames)])
    for i in sorted(args):
        print('ARG', i, sites[i][1], 'at t=%.1f' % args[i][0], args[i][1])
    if flips:
        t_flip = float(re.search(r't=([0-9.]+)', flips[0][1]).group(1))
        for name, seg in (('pre-flip', [f for f in frames if f[1] < t_flip]), ('post-flip', [f for f in frames if f[1] >= t_flip])):
            print(name, 'frames', len(seg), 'ticks', dict(collections.Counter(f[2] for f in seg)), 'g', dict(collections.Counter(f[5] for f in seg)))


# ---- censo dinamico: toda leitura de [0x90177C]/[0x901778]/double 0x8B4270, de qualquer funcao/clone do lift ------
CENSUS_PRE = r"""/* audit_framestep census: wraps vm_read32/vm_read64 of the lifted chunks (diagnostic copy only) */
#include <stdint.h>
extern "C" void s9r_note(int kind, const char* fn);
static inline uint32_t s9r_rd32(uint64_t a, const char* fn) {
    uint32_t v = vm_read32(a);
    uint32_t e = (uint32_t)a;
    if (e == 0x90177Cu) s9r_note(0, fn); else if (e == 0x901778u) s9r_note(1, fn);
    return v;
}
static inline uint64_t s9r_rd64(uint64_t a, const char* fn) {
    uint64_t v = vm_read64(a);
    if ((uint32_t)a == 0x8B4270u) s9r_note(2, fn);
    return v;
}
#define vm_read32(a) s9r_rd32((a), __func__)
#define vm_read64(a) s9r_rd64((a), __func__)
"""

CENSUS_RT = r"""
/* ---- census runtime (tools/audit_framestep.py census) ---- */
extern "C" {
uint32_t s9r_lim_lr;
struct s9r_ent { const char* fn; uint32_t cnt[3], prev[3]; uint64_t tot[3], fw[3]; };
static s9r_ent s9r_tab[512];
void s9r_note(int kind, const char* fn) {
    uint64_t h = ((uint64_t)(uintptr_t)fn >> 3) * 0x9E3779B97F4A7C15ull;
    for (int k = 0; k < 512; k++) {
        s9r_ent* e = &s9r_tab[(h + k) & 511];
        const char* cur = __atomic_load_n(&e->fn, __ATOMIC_ACQUIRE);
        if (!cur) { const char* z = 0; if (__atomic_compare_exchange_n(&e->fn, &z, fn, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) cur = fn; else cur = z; }
        if (cur == fn) { __atomic_fetch_add(&e->cnt[kind], 1u, __ATOMIC_RELAXED); return; }
    }
}
void s9r_frame(uint32_t ticks, uint64_t tid, uint32_t lr) {
    static int on = -1; static uint64_t fr, t0;
    if (on < 0) on = getenv("PS3_EXP_TICKLOG") ? 1 : 0;
    if (!on) return;
    struct timespec ts_; clock_gettime(CLOCK_MONOTONIC, &ts_);
    uint64_t now = (uint64_t)ts_.tv_sec * 1000000000ull + (uint64_t)ts_.tv_nsec;
    if (!t0) t0 = now;
    fr++;
    char buf[3072]; int n = snprintf(buf, sizeof buf, "[S9R] f=%llu t=%.3f ticks=%u lr=0x%X limlr=0x%X g=%u tid=%llu d:", (unsigned long long)fr, (double)(now - t0) / 1e9, ticks, lr, s9r_lim_lr, (unsigned)vm_read32(0x90177C), (unsigned long long)tid);
    for (int i = 0; i < 512; i++) {
        s9r_ent* e = &s9r_tab[i]; if (!e->fn) continue;
        for (int k = 0; k < 3; k++) {
            uint32_t c = __atomic_load_n(&e->cnt[k], __ATOMIC_RELAXED); uint32_t d = c - e->prev[k];
            if (d) { e->prev[k] = c; if (n < (int)sizeof buf - 48) n += snprintf(buf + n, sizeof buf - n, " %s:%c:%u", e->fn, "SMD"[k], d); }
        }
    }
    fprintf(stderr, "%s\n", buf);
}
}
"""


def cmd_census(lift, dst):
    lift, dst = os.path.abspath(lift), os.path.abspath(dst)
    src2 = dst + '.src'
    os.makedirs(src2, exist_ok=True)
    for name in os.listdir(lift):
        d, s = os.path.join(src2, name), os.path.join(lift, name)
        if os.path.lexists(d):
            continue
        if re.fullmatch(r'ppu_recomp_\d+\.cpp', name) or name == 'ppu_recomp.h' or name == 'ppu_stubs.cpp' or name == 'spu_jobs':
            os.symlink(s, d)
    subprocess.check_call([sys.executable, os.path.join(INC, 'probe_ticklog.py'), src2, dst])
    p = os.path.join(dst, 'ppu_recomp_000.cpp')          # probe_ticklog writes the modified chunk 000 as a real file
    c = open(p, errors='surrogateescape').read()
    a = '{ static int s_on = -1; static uint64_t s_calls, s_sum, s_t0;'
    assert c.count(a) == 1
    c = c.replace(a, 's9r_frame((uint32_t)ctx->gpr[3], ctx->thread_id, (uint32_t)ctx->lr);\n        ' + a, 1)
    a = 'void func_000F7CF4(ppu_context* ctx) {\n'
    assert c.count(a) == 1
    c = c.replace(a, a + '        s9r_lim_lr = (uint32_t)ctx->lr;\n', 1)
    c = c.replace('#include "ppu_recomp.h"', '#include "ppu_recomp.h"\nextern "C" uint32_t s9r_lim_lr; extern "C" void s9r_frame(uint32_t, uint64_t, uint32_t);', 1)
    c += CENSUS_RT
    open(p, 'w', errors='surrogateescape').write(c)
    open(os.path.join(dst, 's9r_pre.h'), 'w').write(CENSUS_PRE)
    # cada chunk vira um embrulho: ppu_recomp.h -> macros -> chunk original (o chunk 000 modificado vai para um .inc)
    os.rename(p, os.path.join(dst, 'ppu_recomp_000_mod.inc'))
    for f in sorted(glob.glob(os.path.join(lift, 'ppu_recomp_*.cpp'))):
        n = os.path.basename(f)
        w = os.path.join(dst, n)
        if os.path.lexists(w):
            os.remove(w)
        body = os.path.join(dst, 'ppu_recomp_000_mod.inc') if n == 'ppu_recomp_000.cpp' else f
        open(w, 'w').write('#include "ppu_recomp.h"\n#include "s9r_pre.h"\n#include "%s"\n' % body)
    for name in os.listdir(dst):                         # nenhum objeto reaproveitado: todos os chunks recompilam
        if name.endswith('.o') and name.startswith('ppu_recomp'):
            os.remove(os.path.join(dst, name))
    print('ok', dst, '(census: build every chunk; OUT=... ./build_macos.sh %s)' % dst)


def cmd_analyze_census(log):
    ls, frames, frm = [], [], []
    pre = re.compile(r'^\s*([0-9.]+) (.*)$')
    for raw in open(log, errors='replace'):
        m = pre.match(raw)
        if not m:
            continue
        t, s = float(m.group(1)), m.group(2)
        if 'LoadingScreens/' in s and ".ls'" in s and '/eng/' not in s:
            ls.append(t)
        mm = re.match(r'\[S9R\] f=(\d+) t=([0-9.]+) ticks=(\d+) lr=0x([0-9A-F]+) limlr=0x([0-9A-F]+) g=(\d+) tid=(\d+) d:(.*)', s)
        if mm:
            d = collections.Counter()
            for kv in mm.group(8).split():
                fn, k, c = kv.rsplit(':', 2)
                if fn in ('rame', 's9r_frame'):      # a propria leitura do gancho de quadro (g=...), nao do jogo
                    continue
                d[(fn, k)] += int(c)
            frames.append((t, int(mm.group(3)), int(mm.group(4), 16), int(mm.group(5), 16), int(mm.group(6)), d))
        elif s.startswith('[FRMODE]'):
            frm.append((t, s.strip()))
    lvl = [x for x in ls if x > 55]
    t_lvl = lvl[0] if lvl else None

    def phase(t):
        if t_lvl is not None and t >= t_lvl + 20:
            return 'G'
        if t_lvl is not None and t >= t_lvl:
            return 'L'
        if len(ls) >= 2 and t >= ls[1]:
            return 'B'
        return 'A'
    ph = collections.defaultdict(list)
    for fr in frames:
        ph[phase(fr[0])].append(fr)
    print('log', log, 'frames', len(frames), '.ls opens (t):', ls, 'phase frames:', {k: len(v) for k, v in ph.items()})
    for t, s in frm[:10]:
        print('  ', t, s)
    keys = sorted({k for fr in frames for k in fr[5]})
    print('%-18s %-4s | reads/frames-with/max (pct) per phase A B L G   [S=[0x90177C] M=[0x901778] D=double 0x8B4270]' % ('function', 'kind'))
    for k in keys:
        row = []
        for p in 'ABLG':
            v = ph.get(p, [])
            r = sum(f[5].get(k, 0) for f in v)
            fw = sum(1 for f in v if f[5].get(k, 0))
            mx = max([f[5].get(k, 0) for f in v] or [0])
            row.append('%d/%d/%d (%d%%)' % (r, fw, mx, (100 * fw // len(v)) if v else 0))
        print('%-18s %-4s | %s' % (k[0] if k[0].startswith('func_') else 'func_' + k[0], k[1], ' | '.join(row)))


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'scan':
        cmd_scan(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == 'instrument':
        cmd_instrument(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == 'census':
        cmd_census(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == 'analyze-census':
        cmd_analyze_census(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == 'analyze':
        mp = sys.argv[sys.argv.index('--map') + 1] if '--map' in sys.argv else None
        if not mp:
            sys.exit('analyze needs --map <out_lift>_sites.txt (written by instrument)')
        cmd_analyze(sys.argv[2], mp)
    else:
        sys.exit(__doc__)
