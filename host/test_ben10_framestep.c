/*
 * Unit test of host/ben10_framestep.c (plan 2026-09-30-ben10-60fps.md, Task 2).
 *   clang -std=c11 -Wall -Wextra -Ihost host/test_ben10_framestep.c host/ben10_framestep.c -lm \
 *         -o /tmp/t_fs && /tmp/t_fs
 * Pure host unit: no guest, no runtime library.
 */
#include "ben10_framestep.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_fail, g_checks;
#define CHECK(c) do { g_checks++; if (!(c)) { g_fail++; \
    printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

/* ---- parsing / OFF ---- */
static void test_parse_and_off(void)
{
    CHECK(ben10_fs_parse_policy(NULL) == BEN10_FS_OFF);
    CHECK(ben10_fs_parse_policy("") == BEN10_FS_OFF);
    CHECK(ben10_fs_parse_policy("0") == BEN10_FS_OFF);
    CHECK(ben10_fs_parse_policy("45") == BEN10_FS_OFF);
    CHECK(ben10_fs_parse_policy("AUTO") == BEN10_FS_OFF);   /* exact match only */
    CHECK(ben10_fs_parse_policy("30") == BEN10_FS_FIXED30);
    CHECK(ben10_fs_parse_policy("60") == BEN10_FS_FIXED60);
    CHECK(ben10_fs_parse_policy("auto-p") == BEN10_FS_AUTO_P);
    CHECK(ben10_fs_parse_policy("auto-m") == BEN10_FS_AUTO_M);
    CHECK(ben10_fs_parse_policy("auto") == BEN10_FS_AUTO_DEFAULT);
    CHECK(BEN10_FS_AUTO_DEFAULT == BEN10_FS_AUTO_M);        /* Task 1 verdict */

    ben10_fs st;
    ben10_fs_init(&st, BEN10_FS_OFF);
    CHECK(!ben10_fs_active(&st));
    CHECK(ben10_fs_frame(&st, 16.7, 16.7) == 0);
    CHECK(ben10_fs_ticks(&st) == 0);
    CHECK(ben10_fs_game_mode(&st) == -1);
    CHECK(st.frames == 0);                                  /* OFF accounts nothing */
}

/* ---- fixed ---- */
static void test_fixed(void)
{
    ben10_fs a, b;
    ben10_fs_init(&a, BEN10_FS_FIXED30);
    ben10_fs_init(&b, BEN10_FS_FIXED60);
    CHECK(ben10_fs_active(&a) && ben10_fs_active(&b));
    CHECK(ben10_fs_ticks(&a) == 20 && ben10_fs_ticks(&b) == 10);
    CHECK(ben10_fs_game_mode(&a) == 0 && ben10_fs_game_mode(&b) == 1);
    const double w[] = {1.0, 16.7, 33.4, 60.0, 500.0, 0.0, -5.0};
    for (size_t i = 0; i < sizeof w / sizeof w[0]; i++) {
        CHECK(ben10_fs_frame(&a, w[i], -1) == 20);
        CHECK(ben10_fs_frame(&b, w[i], -1) == 10);
    }
    CHECK(a.frames == 7 && a.ticks == 140 && b.ticks == 70);
}

/* ---- policy P ---- */
static void test_p_basic(void)
{
    ben10_fs st;
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    CHECK(ben10_fs_game_mode(&st) == 1);                    /* 59.94 limiter */
    CHECK(ben10_fs_ticks(&st) == 10);
    /* steady 16.7 ms -> always 10. 16.7 ms is 10.02 ticks: the 0.02 ticks/frame of skew
     * piles up to the half-quantum threshold only after ~250 frames (see the drift test). */
    for (int i = 0; i < 200; i++) CHECK(ben10_fs_frame(&st, 16.7, -1) == 10);
    /* steady 33.4 ms (20.04 ticks) -> 20 until the 0.04 ticks/frame of skew reaches the
     * half-quantum threshold (~125 frames); 100 frames here */
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    for (int i = 0; i < 100; i++) CHECK(ben10_fs_frame(&st, 33.4, -1) == 20);
    /* 60 ms frames (< 20 fps): capped at 30, console-like slow motion */
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    for (int i = 0; i < 600; i++) CHECK(ben10_fs_frame(&st, 60.0, -1) == 30);
    CHECK(st.debt <= BEN10_FS_DEBT_MAX + 1e-9);             /* does not grow without bound */
    /* 8 ms frames (faster than 60 Hz): never below 10 ticks */
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    for (int i = 0; i < 600; i++) CHECK(ben10_fs_frame(&st, 8.0, -1) == 10);
    CHECK(st.debt >= BEN10_FS_DEBT_MIN - 1e-9);
    /* garbage input does not break the invariants */
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    CHECK(ben10_fs_frame(&st, -3.0, -1) == 10);
    CHECK(ben10_fs_frame(&st, NAN, -1) == 10);
    CHECK(ben10_fs_frame(&st, INFINITY, -1) == 30);
    CHECK(isfinite(st.debt));
}

static void test_p_longrun(void)
{
    /* alternating 16.7 / 25 ms: sum(ticks)/600 within +-10 ticks of sum(wall) */
    ben10_fs st;
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    double wall = 0;
    for (int i = 0; i < 6000; i++) {
        double w = (i & 1) ? 25.0 : 16.7;
        wall += w;
        uint32_t k = ben10_fs_frame(&st, w, -1);
        CHECK(k == 10 || k == 20 || k == 30);
    }
    double want = wall * 0.6;                                /* ticks of the wall time */
    CHECK(fabs((double)st.ticks - want) <= 10.0);
    printf("  P alternating 16.7/25: ticks=%llu want=%.1f diff=%.2f hist=%llu/%llu/%llu\n",
           (unsigned long long)st.ticks, want, (double)st.ticks - want,
           (unsigned long long)st.hist[1], (unsigned long long)st.hist[2],
           (unsigned long long)st.hist[3]);

    /* pseudo-random 12..45 ms frames (LCG, deterministic): same bound */
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    uint32_t r = 12345; wall = 0;
    for (int i = 0; i < 20000; i++) {
        r = r * 1664525u + 1013904223u;
        double w = 17.0 + (double)((r >> 8) % 2800) / 100.0; /* 17..45 ms: debt stays unclamped */
        wall += w;
        (void)ben10_fs_frame(&st, w, -1);
    }
    CHECK(fabs((double)st.ticks - wall * 0.6) <= 10.0);
    /* speed = sum(ticks)/600 / sum(wall) ~ 1.0 */
    double speed = ((double)st.ticks / 600.0) / (wall / 1000.0);
    CHECK(fabs(speed - 1.0) < 0.002);
}

/* The game's own 59.94 Hz period (16.6834 ms) is 10.01 ticks: 0.01 ticks/frame of skew that the
 * accumulator repays with one 20-tick frame every ~500 frames (~8 s). Documented, not hidden. */
static void test_p_drift_at_game_period(void)
{
    ben10_fs st;
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    const double period = 1000.0 / 59.94;
    for (int i = 0; i < 400; i++) CHECK(ben10_fs_frame(&st, period, -1) == 10);
    ben10_fs_init(&st, BEN10_FS_AUTO_P);
    for (int i = 0; i < 6000; i++) (void)ben10_fs_frame(&st, period, -1);
    printf("  P at the game's 59.94 Hz period, 6000 frames: k1/k2/k3=%llu/%llu/%llu\n",
           (unsigned long long)st.hist[1], (unsigned long long)st.hist[2],
           (unsigned long long)st.hist[3]);
    CHECK(st.hist[1] >= 5900 && st.hist[3] == 0);              /* >= 98 % at step 10 */
    CHECK(fabs((double)st.ticks - 6000.0 * period * 0.6) <= 10.0);
}

/* ---- policy M ---- */
/* one frame of the M simulation: advance by `period` ms, work `work` ms */
static uint32_t mstep(ben10_fs *st, double period, double work)
{
    return ben10_fs_frame(st, period, work);
}

static void test_m_promote(void)
{
    ben10_fs st;
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    CHECK(ben10_fs_game_mode(&st) == 0 && ben10_fs_ticks(&st) == 20);   /* starts safe */
    /* machine can do 12 ms/frame, but in 30 Hz the period is 33.3 ms (limiter):
     * M must judge the WORK time. 29 frames = 966 ms: not yet. */
    for (int i = 0; i < 29; i++) mstep(&st, 33.3, 12.0);
    CHECK(ben10_fs_game_mode(&st) == 0);
    for (int i = 0; i < 3; i++) mstep(&st, 33.3, 12.0);                 /* 1099 ms */
    CHECK(ben10_fs_game_mode(&st) == 1);
    CHECK(ben10_fs_ticks(&st) == 10);
    CHECK(st.flips == 1);
    /* exactly at the threshold: p95 == 16.0 still passes */
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    for (int i = 0; i < 40; i++) mstep(&st, 33.3, 16.0);
    CHECK(ben10_fs_game_mode(&st) == 1);
}

static void test_m_no_promote(void)
{
    ben10_fs st;
    /* p95 just above 16 ms: 10% of the frames at 20 ms -> never promotes */
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    for (int i = 0; i < 600; i++) mstep(&st, 33.3, (i % 10 == 0) ? 20.0 : 12.0);
    CHECK(ben10_fs_game_mode(&st) == 0 && st.flips == 0);
    /* a slow machine (work 30 ms) never promotes */
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    for (int i = 0; i < 600; i++) mstep(&st, 33.3, 30.0);
    CHECK(ben10_fs_game_mode(&st) == 0 && st.flips == 0);
    /* p95 is a quantile, not a max: ONE slow frame among the ~31 of the 1 s window is inside it */
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    for (int i = 0; i < 31; i++) mstep(&st, 33.3, (i == 10) ? 25.0 : 12.0);
    CHECK(ben10_fs_game_mode(&st) == 1);
    /* TWO slow frames in that same window are not */
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    for (int i = 0; i < 31; i++) mstep(&st, 33.3, (i == 10 || i == 20) ? 25.0 : 12.0);
    CHECK(ben10_fs_game_mode(&st) == 0);
}

static ben10_fs *to60(ben10_fs *st)
{
    ben10_fs_init(st, BEN10_FS_AUTO_M);
    for (int i = 0; i < 40 && ben10_fs_game_mode(st) == 0; i++) mstep(st, 33.3, 12.0);
    return st;
}

static void test_m_demote(void)
{
    ben10_fs st;
    /* 3 frames > 17.5 ms within 0.5 s -> back to 30. First wait out the flip
     * rate window so only the demotion rule is exercised. */
    to60(&st);
    CHECK(ben10_fs_game_mode(&st) == 1);
    for (int i = 0; i < 70; i++) mstep(&st, 16.7, 12.0);                /* 1.17 s of good frames */
    CHECK(ben10_fs_game_mode(&st) == 1);
    mstep(&st, 16.7, 18.0);
    mstep(&st, 16.7, 18.0);
    CHECK(ben10_fs_game_mode(&st) == 1);                                /* 2 slow: not yet */
    mstep(&st, 16.7, 18.0);
    CHECK(ben10_fs_game_mode(&st) == 0);                                /* 3rd: demote */
    CHECK(ben10_fs_ticks(&st) == 20);
    CHECK(st.flips == 2);

    /* 3 slow frames spread over more than 0.5 s do not demote */
    to60(&st);
    for (int i = 0; i < 70; i++) mstep(&st, 16.7, 12.0);
    for (int n = 0; n < 3; n++) {
        mstep(&st, 16.7, 18.0);
        for (int i = 0; i < 40; i++) mstep(&st, 16.7, 12.0);            /* 0.67 s apart */
    }
    CHECK(ben10_fs_game_mode(&st) == 1);

    /* exactly 17.5 is not slow (strictly greater) */
    to60(&st);
    for (int i = 0; i < 70; i++) mstep(&st, 16.7, 12.0);
    for (int i = 0; i < 10; i++) mstep(&st, 16.7, 17.5);
    CHECK(ben10_fs_game_mode(&st) == 1);
}

static void test_m_slow_frames_before_flip_dont_count(void)
{
    /* slow frames that happened BEFORE the promotion are not evidence against it.
     * 60 frames of 16.7 ms (the caller may feed any period): 3 slow ones at 52..54 are
     * inside p95 (60 samples tolerate 3), the promotion fires at frame 60 with all three
     * still inside the last 0.5 s; the next frames must not demote. */
    ben10_fs st;
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    for (int i = 0; i < 59; i++) mstep(&st, 16.7, (i >= 52 && i <= 54) ? 18.0 : 12.0);
    CHECK(ben10_fs_game_mode(&st) == 0);
    mstep(&st, 16.7, 12.0);                                  /* t = 1002 ms */
    CHECK(ben10_fs_game_mode(&st) == 1 && st.flips == 1);
    for (int i = 0; i < 20; i++) mstep(&st, 16.7, 12.0);
    CHECK(ben10_fs_game_mode(&st) == 1 && st.flips == 1);
}

static void test_m_flip_rate(void)
{
    /* adversarial pattern: good phases and bad phases of random length; never more
     * than 2 flips inside any 1 s window, over a long run. */
    ben10_fs st;
    ben10_fs_init(&st, BEN10_FS_AUTO_M);
    double t = 0, flip_t[4096]; int nf = 0;
    int prev = ben10_fs_game_mode(&st);
    uint32_t r = 777; int good = 1; int left = 50;
    for (int i = 0; i < 40000; i++) {
        if (--left <= 0) {
            r = r * 1664525u + 1013904223u;
            good = !good;
            left = 3 + (int)((r >> 8) % 90);
        }
        double period = prev ? 16.7 : 33.3;
        double work = good ? 10.0 : 25.0;
        if (work > period) period = work;
        t += period;
        (void)mstep(&st, period, work);
        int m = ben10_fs_game_mode(&st);
        if (m != prev) { if (nf < 4096) flip_t[nf++] = t; prev = m; }
    }
    int worst = 0;
    for (int i = 0; i < nf; i++) {
        int c = 0;
        for (int j = i; j < nf && flip_t[j] - flip_t[i] < 1000.0; j++) c++;
        if (c > worst) worst = c;
    }
    printf("  M adversarial: flips=%d worst-per-1s-window=%d\n", nf, worst);
    CHECK(nf >= 4);                                          /* the pattern does exercise flips */
    CHECK(worst <= 2);
    CHECK(st.flips == (uint32_t)nf);
}

static void test_m_demote_blocked_by_rate(void)
{
    /* promote, then terrible frames right away: the 2-flips-per-second cap holds
     * the demotion until the window frees (promote at t~1.1s -> demote allowed
     * only when it keeps <= 2 flips in 1 s: 1 flip so far, so it IS allowed;
     * but a 3rd flip inside 1 s after the 2nd is not). */
    ben10_fs st;
    to60(&st);                                               /* flip 1 */
    for (int i = 0; i < 5; i++) mstep(&st, 40.0, 40.0);      /* 3+ slow frames -> flip 2 */
    CHECK(ben10_fs_game_mode(&st) == 0 && st.flips == 2);
    /* in 30 Hz again, instantly excellent frames: promotion needs 1 s of fresh data,
     * so no 3rd flip inside 1 s of the 2nd. */
    for (int i = 0; i < 20; i++) mstep(&st, 33.3, 8.0);      /* 0.67 s */
    CHECK(st.flips == 2);
}

static void test_format(void)
{
    ben10_fs st;
    char buf[256];
    ben10_fs_init(&st, BEN10_FS_FIXED60);
    for (int i = 0; i < 60; i++) ben10_fs_frame(&st, 16.7, -1);
    int n = ben10_fs_format(&st, buf, sizeof buf);
    CHECK(n > 0 && (size_t)n < sizeof buf);
    CHECK(strstr(buf, "[FRAMESTEP]") != NULL);
    CHECK(strstr(buf, "frames=60") != NULL);
    CHECK(strstr(buf, "ticks=600") != NULL);
    CHECK(strstr(buf, "hist k1/k2/k3=60/0/0") != NULL);
    CHECK(strstr(buf, "game_s/wall_s=0.99") != NULL);        /* 1.0 s of ticks / 1.002 s wall */
    printf("  %s\n", buf);
}

int main(void)
{
    test_parse_and_off();
    test_fixed();
    test_p_basic();
    test_p_longrun();
    test_p_drift_at_game_period();
    test_m_promote();
    test_m_no_promote();
    test_m_demote();
    test_m_slow_frames_before_flip_dont_count();
    test_m_flip_rate();
    test_m_demote_blocked_by_rate();
    test_format();
    printf("%s: %d checks, %d failed\n", g_fail ? "FAIL" : "PASS", g_checks, g_fail);
    return g_fail ? 1 : 0;
}
