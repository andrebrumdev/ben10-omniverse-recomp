/*
 * Ben 10 Omniverse (BLUS31017): frame-step policy, a pure host unit.
 *
 * Context (ps3recomp docs/superpowers/plans/2026-09-30-ben10-60fps.md):
 * the game's logic is fixed-step per frame, in ticks of 1/600 s. The game
 * ships three steps of its own: 10 ticks (mode 1, 59.94 Hz), 20 ticks
 * (mode 0, 29.97 Hz, the default of this boot) and 30 ticks (mode 2, 20 Hz).
 * This unit only DECIDES which step to use; it owns no guest state and calls
 * nothing. The mid-asm hook (Task 3) feeds it frame times and writes the answer.
 *
 * Policies (env PS3_BEN10_FPS):
 *   unset / "" / unknown  OFF     no effect (the hook returns immediately)
 *   "30"                  FIXED30 always 20 ticks (game mode 0)
 *   "60"                  FIXED60 always 10 ticks (game mode 1)
 *   "auto-p"              AUTO_P  policy P: per-frame step 10/20/30 from an
 *                                 accumulator of wall time (game mode 1 limiter).
 *                                 Task 1 REFUTED this in-boot (the scene loop caches
 *                                 the step at entry); kept for A/B and for a future
 *                                 "S4" hook that refreshes the cache.
 *   "auto-m"              AUTO_M  policy M: whole-mode switch 30 <-> 60 with
 *                                 hysteresis. The new mode is only SAFE to apply
 *                                 through the game's own setter at a scene boundary
 *                                 (Task 1 verdict), so ben10_fs_game_mode() is what the
 *                                 setter hook writes; ben10_fs_frame() keeps reporting
 *                                 the step of the current decision.
 *   "auto"                AUTO_M  (BEN10_FS_AUTO_DEFAULT: the Task 1 verdict picks M).
 */
#ifndef BEN10_FRAMESTEP_H
#define BEN10_FRAMESTEP_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    BEN10_FS_OFF = 0,
    BEN10_FS_FIXED30,
    BEN10_FS_FIXED60,
    BEN10_FS_AUTO_P,
    BEN10_FS_AUTO_M
} ben10_fs_policy;

/* What plain "auto" means: the Task 1 verdict (M at scene boundaries). */
#define BEN10_FS_AUTO_DEFAULT BEN10_FS_AUTO_M

/* Policy P: ticks = 10*k, k in [1,3]. */
#define BEN10_FS_TICK_QUANTUM   10
#define BEN10_FS_K_MAX          3
/* Debt bounds (ticks): below -10 the machine is simply faster than 59.94 Hz
 * (the limiter paces it); above +20 the game is below 20 fps and runs in slow
 * motion exactly as on the console, instead of the debt growing forever. */
#define BEN10_FS_DEBT_MIN      (-10.0)
#define BEN10_FS_DEBT_MAX        20.0

/* Policy M thresholds (ms) and windows. */
#define BEN10_FS_M_PROMOTE_MS     1000.0  /* fresh evidence before 30 -> 60 */
#define BEN10_FS_M_PROMOTE_P95_MS   16.0  /* p95 of the work time must be <= this */
#define BEN10_FS_M_DEMOTE_MS       500.0  /* window for the slow-frame count */
#define BEN10_FS_M_DEMOTE_FRAME_MS  17.5  /* a frame slower than this is "slow" */
#define BEN10_FS_M_DEMOTE_COUNT       3   /* slow frames in the window to demote */
#define BEN10_FS_M_FLIP_WINDOW_MS  1000.0 /* at most BEN10_FS_M_MAX_FLIPS in it */
#define BEN10_FS_M_MAX_FLIPS          2
#define BEN10_FS_RING 512

typedef struct {
    ben10_fs_policy policy;
    /* policy P */
    double debt;             /* ticks owed: sum(0.6*wall_ms) - sum(ticks) (clamped) */
    /* policy M */
    int    mode;             /* 0 = 30 Hz (20 ticks), 1 = 60 Hz (10 ticks) */
    double t_ms;             /* sum of wall_ms (the unit's own clock) */
    double since_ms;         /* clock at the last flip (or start) */
    double flip_t[BEN10_FS_M_MAX_FLIPS]; /* last flips, [0] oldest; <0 = none */
    uint32_t flips;
    double   ring_t[BEN10_FS_RING];      /* sample clock */
    double   ring_w[BEN10_FS_RING];      /* sample work ms */
    uint32_t ring_head, ring_n;
    /* accounting (all policies) */
    uint64_t frames, ticks;
    double   wall_ms;
    uint64_t hist[BEN10_FS_K_MAX + 1];   /* hist[k] frames with step 10*k */
    uint32_t hist_last_k;                /* policy P: k of the last frame */
} ben10_fs;

/* "30"/"60"/"auto"/"auto-p"/"auto-m" -> policy; NULL/""/anything else -> OFF. */
ben10_fs_policy ben10_fs_parse_policy(const char *s);
/* PS3_BEN10_FPS from the environment, through ben10_fs_parse_policy. */
ben10_fs_policy ben10_fs_policy_from_env(void);

void ben10_fs_init(ben10_fs *st, ben10_fs_policy policy);
int  ben10_fs_active(const ben10_fs *st);          /* policy != OFF */

/*
 * One frame finished. wall_ms = the frame period (what the accumulator of P
 * pays). work_ms = the time the machine needed for the frame WITHOUT the game's
 * limiter wait (what M judges: in 30 Hz mode the period is 33 ms even on a
 * machine that could do 10); work_ms < 0 means "same as wall_ms".
 * Returns the step in ticks for the NEXT frame: 10, 20 or 30 (0 when OFF).
 */
uint32_t ben10_fs_frame(ben10_fs *st, double wall_ms, double work_ms);

/* Step the current decision gives (what ben10_fs_frame returned last; the
 * initial step before any frame). 0 when OFF. */
uint32_t ben10_fs_ticks(const ben10_fs *st);

/* The game's mode word for the setter hook: 0 = 30 Hz, 1 = 60 Hz,
 * -1 = OFF (do not touch). FIXED60 and AUTO_P return 1 (59.94 limiter);
 * AUTO_M returns its current decision. */
int ben10_fs_game_mode(const ben10_fs *st);

/* "[FRAMESTEP] policy=.. mode=.. frames=.. ticks=.. game_s/wall_s=.. hist k1/k2/k3=a/b/c" */
int ben10_fs_format(const ben10_fs *st, char *buf, size_t n);

#ifdef __cplusplus
}
#endif
#endif
