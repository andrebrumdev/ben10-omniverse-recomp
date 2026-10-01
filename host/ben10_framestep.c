/*
 * Ben 10 Omniverse frame-step policy (see ben10_framestep.h). Pure: no guest
 * access, no I/O, no libm. Single-threaded by contract (called from the game's
 * main thread at the frame boundary).
 */
#include "ben10_framestep.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_MS 10000.0   /* a stall longer than this is clamped (loading screens, suspend) */

static double clean_ms(double v)
{
    if (!(v > 0.0)) return 0.0;      /* negative, zero and NaN */
    if (v > MAX_MS) return MAX_MS;   /* includes +inf */
    return v;
}

ben10_fs_policy ben10_fs_parse_policy(const char *s)
{
    if (!s) return BEN10_FS_OFF;
    if (!strcmp(s, "30"))     return BEN10_FS_FIXED30;
    if (!strcmp(s, "60"))     return BEN10_FS_FIXED60;
    if (!strcmp(s, "auto-p")) return BEN10_FS_AUTO_P;
    if (!strcmp(s, "auto-m")) return BEN10_FS_AUTO_M;
    if (!strcmp(s, "auto"))   return BEN10_FS_AUTO_DEFAULT;
    return BEN10_FS_OFF;
}

ben10_fs_policy ben10_fs_policy_from_env(void)
{
    return ben10_fs_parse_policy(getenv("PS3_BEN10_FPS"));
}

void ben10_fs_init(ben10_fs *st, ben10_fs_policy policy)
{
    memset(st, 0, sizeof *st);
    st->policy = policy;
    st->flip_t[0] = st->flip_t[1] = -1.0;
}

int ben10_fs_active(const ben10_fs *st)
{
    return st->policy != BEN10_FS_OFF;
}

uint32_t ben10_fs_ticks(const ben10_fs *st)
{
    switch (st->policy) {
    case BEN10_FS_FIXED30: return 2 * BEN10_FS_TICK_QUANTUM;
    case BEN10_FS_FIXED60: return BEN10_FS_TICK_QUANTUM;
    case BEN10_FS_AUTO_P:  return st->frames ? BEN10_FS_TICK_QUANTUM * (uint32_t)st->hist_last_k
                                             : BEN10_FS_TICK_QUANTUM;
    case BEN10_FS_AUTO_M:  return st->mode ? BEN10_FS_TICK_QUANTUM : 2 * BEN10_FS_TICK_QUANTUM;
    default:               return 0;
    }
}

int ben10_fs_game_mode(const ben10_fs *st)
{
    switch (st->policy) {
    case BEN10_FS_FIXED30: return 0;
    case BEN10_FS_FIXED60:
    case BEN10_FS_AUTO_P:  return 1;
    case BEN10_FS_AUTO_M:  return st->mode;
    default:               return -1;
    }
}

/* ---- policy P ---- */
static uint32_t p_step(ben10_fs *st, double wall)
{
    st->debt += wall * 0.6;                       /* 600 ticks/s = 0.6 ticks/ms */
    double x = st->debt / (double)BEN10_FS_TICK_QUANTUM + 0.5;   /* round half up */
    int k = (x < 1.0) ? 1 : (x >= (double)BEN10_FS_K_MAX) ? BEN10_FS_K_MAX : (int)x;
    st->debt -= (double)(k * BEN10_FS_TICK_QUANTUM);
    if (st->debt < BEN10_FS_DEBT_MIN) st->debt = BEN10_FS_DEBT_MIN;
    if (st->debt > BEN10_FS_DEBT_MAX) st->debt = BEN10_FS_DEBT_MAX;
    return (uint32_t)k;
}

/* ---- policy M ---- */
static int m_flip_allowed(const ben10_fs *st)
{
    /* at most BEN10_FS_M_MAX_FLIPS flips in any 1 s window: a new flip needs the
     * older of the last two to be at least one window old. With the current thresholds
     * the hysteresis already implies it (a promotion needs 1 s of fresh evidence, a demotion
     * only follows a promotion), so this is a guard that keeps the contract if they change. */
    if (st->flips < BEN10_FS_M_MAX_FLIPS) return 1;
    return (st->t_ms - st->flip_t[0]) >= BEN10_FS_M_FLIP_WINDOW_MS;
}

static void m_flip(ben10_fs *st)
{
    st->mode = !st->mode;
    st->flips++;
    st->flip_t[0] = st->flip_t[1];
    st->flip_t[1] = st->t_ms;
    st->since_ms = st->t_ms;
}

static int cmp_d(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

/* p95 of the work time of the samples in (t-window, t]; returns -1 when the
 * evidence is not enough. */
static double m_p95(const ben10_fs *st, double window)
{
    double v[BEN10_FS_RING];
    uint32_t n = 0;
    double oldest = st->t_ms;
    for (uint32_t i = 0; i < st->ring_n; i++) {
        uint32_t idx = (st->ring_head + BEN10_FS_RING - 1 - i) % BEN10_FS_RING;
        if (st->ring_t[idx] <= st->t_ms - window) break;
        v[n++] = st->ring_w[idx];
        oldest = st->ring_t[idx];
    }
    if (n == 0) return -1.0;
    /* the ring overflowed inside the window: do not judge on a truncated window */
    if (st->ring_n == BEN10_FS_RING && n == BEN10_FS_RING && oldest > st->t_ms - window)
        return -1.0;
    qsort(v, n, sizeof v[0], cmp_d);
    uint32_t idx = (n * 95u + 99u) / 100u - 1u;   /* ceil(0.95 n) - 1 */
    return v[idx];
}

static uint32_t m_count_slow(const ben10_fs *st)
{
    double from = st->t_ms - BEN10_FS_M_DEMOTE_MS;
    if (st->since_ms > from) from = st->since_ms;   /* only evidence from this mode */
    uint32_t c = 0;
    for (uint32_t i = 0; i < st->ring_n; i++) {
        uint32_t idx = (st->ring_head + BEN10_FS_RING - 1 - i) % BEN10_FS_RING;
        if (st->ring_t[idx] <= from) break;
        if (st->ring_w[idx] > BEN10_FS_M_DEMOTE_FRAME_MS) c++;
    }
    return c;
}

static void m_step(ben10_fs *st, double wall, double work)
{
    st->t_ms += wall;
    st->ring_t[st->ring_head] = st->t_ms;
    st->ring_w[st->ring_head] = work;
    st->ring_head = (st->ring_head + 1) % BEN10_FS_RING;
    if (st->ring_n < BEN10_FS_RING) st->ring_n++;

    if (!m_flip_allowed(st)) return;
    if (st->mode == 0) {
        if (st->t_ms - st->since_ms >= BEN10_FS_M_PROMOTE_MS) {
            double p95 = m_p95(st, BEN10_FS_M_PROMOTE_MS);
            if (p95 >= 0.0 && p95 <= BEN10_FS_M_PROMOTE_P95_MS) m_flip(st);
        }
    } else {
        if (m_count_slow(st) >= BEN10_FS_M_DEMOTE_COUNT) m_flip(st);
    }
}

uint32_t ben10_fs_frame(ben10_fs *st, double wall_ms, double work_ms)
{
    if (st->policy == BEN10_FS_OFF) return 0;
    double wall = clean_ms(wall_ms);
    double work = (work_ms < 0.0 || work_ms != work_ms) ? wall : clean_ms(work_ms);
    uint32_t ticks;
    switch (st->policy) {
    case BEN10_FS_FIXED30: ticks = 2 * BEN10_FS_TICK_QUANTUM; break;
    case BEN10_FS_FIXED60: ticks = BEN10_FS_TICK_QUANTUM; break;
    case BEN10_FS_AUTO_P: {
        uint32_t k = p_step(st, wall);
        st->hist_last_k = k;
        ticks = k * BEN10_FS_TICK_QUANTUM;
        break;
    }
    default:
        m_step(st, wall, work);
        ticks = st->mode ? BEN10_FS_TICK_QUANTUM : 2 * BEN10_FS_TICK_QUANTUM;
        break;
    }
    st->frames++;
    st->ticks += ticks;
    st->wall_ms += wall;
    st->hist[ticks / BEN10_FS_TICK_QUANTUM]++;
    return ticks;
}

static const char *policy_name(ben10_fs_policy p)
{
    switch (p) {
    case BEN10_FS_FIXED30: return "30";
    case BEN10_FS_FIXED60: return "60";
    case BEN10_FS_AUTO_P:  return "auto-p";
    case BEN10_FS_AUTO_M:  return "auto-m";
    default:               return "off";
    }
}

int ben10_fs_format(const ben10_fs *st, char *buf, size_t n)
{
    double speed = st->wall_ms > 0.0 ? ((double)st->ticks / 600.0) / (st->wall_ms / 1000.0) : 0.0;
    return snprintf(buf, n,
        "[FRAMESTEP] policy=%s mode=%d frames=%llu ticks=%llu game_s/wall_s=%.3f flips=%u "
        "hist k1/k2/k3=%llu/%llu/%llu",
        policy_name(st->policy), ben10_fs_game_mode(st),
        (unsigned long long)st->frames, (unsigned long long)st->ticks, speed, st->flips,
        (unsigned long long)st->hist[1], (unsigned long long)st->hist[2],
        (unsigned long long)st->hist[3]);
}
