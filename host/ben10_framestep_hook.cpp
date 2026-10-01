/*
 * Ben 10 Omniverse (BLUS31017): mid-asm hooks of the 60 fps plan (Task 3).
 *   ppu_lifter.py --config recomp.toml emits `gow2_midasm_<Name>(ctx);` beside the anchored guest
 *   instruction (the prefix is the engine's, fixed in tools/ppu_lifter.py MIDASM_SYMBOL_PREFIX).
 *
 * Everything is gated by PS3_BEN10_FPS (host/ben10_framestep.h). Unset = every hook returns
 * on its first line: no guest register or memory is touched and nothing is logged.
 *
 * What the hooks do (docs/superpowers/plans/2026-09-30-ben10-60fps.md; evidence in the port's
 * notes/2026-10-xx-framestep-audit.md, Task 1: the scene loop caches the step at ENTRY, so a
 * mid-scene switch is unsafe; the safe point is the game's own mode setter at a scene boundary):
 *
 *  - Ben10ModeR3 / Ben10ModeR0: AFTER the instruction that loads the game's mode word from its
 *    config (`lwz r3,0x18(r3)` at 0x583E4 inside func_000583D8, `lwz r0,0x18(r3)` at 0xB2638 =
 *    first instruction of func_000B2638). They replace the loaded value in the register with
 *    the policy's mode (0 = 30 Hz / 20 ticks, 1 = 59.94 Hz / 10 ticks). The GAME's own setter
 *    then produces the mode, the step ([0x90177C]) and the limiter period (double 0x8B4270)
 *    before the scene loop reads them. No guest memory is written, no guest function is
 *    called, nothing is poked afterwards.
 *  - Ben10LimiterEnter (entry of func_000F7CF4) and Ben10FrameStep (right before the logic
 *    advance `bl func_000B5C4C` at 0xF7FDC): OBSERVE only. They time the frame and the work
 *    without the limiter wait, feed the policy and log `[FRAMESTEP]` once per second. They never
 *    touch r3 (the ticks the game passes to the advance stay the game's own).
 *
 * Policy M (`auto`) can only change the mode at the NEXT setter call (a scene boundary): its
 * decision matures from the frames of the previous scenes.
 */
#include "ben10_framestep.h"

#include "ppu_context.h"
#include "ppu_memory.h"   /* vm_read32 (static inline) */

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#if defined(__GNUC__) || defined(__clang__)
#  define B10_USED __attribute__((used))
#else
#  define B10_USED
#endif

namespace {

struct State {
    ben10_fs     fs;
    ben10_fs_obs obs;
    int          active;
    /* The policy and the observer are single-threaded units, fed from the game's frame loop.
     * Nothing proves statically that no other guest thread reaches an observing hook, so they run
     * under a mutex (never held across a guest call or a vm_* access: the bodies call no guest code,
     * so they cannot re-enter) and a call from a second thread is logged once; its frames are still accounted
     * (dropping them could silence the real frame loop if the wrong thread arrived first). The
     * setter hooks run wherever the game calls its setter: they read the decision through an
     * atomic mirror, published by the observing hook. */
    int               decision;       /* __atomic_* builtins: <atomic> clashes with the runtime's <stdatomic.h> */
    pthread_mutex_t   mu;
    int               owner_set;
    pthread_t         owner;
    int               foreign_calls;
    State() : decision(-1), mu(PTHREAD_MUTEX_INITIALIZER), owner_set(0), owner(), foreign_calls(0) {
        ben10_fs_init(&fs, ben10_fs_policy_from_env());
        ben10_fs_obs_init(&obs);
        active = ben10_fs_active(&fs);
        __atomic_store_n(&decision, ben10_fs_game_mode(&fs), __ATOMIC_RELAXED);
        if (active) {
            const char *e = getenv("PS3_BEN10_FPS");
            fprintf(stderr, "[FRAMESTEP] enabled PS3_BEN10_FPS=%s decision_mode=%d\n",
                    e ? e : "", ben10_fs_game_mode(&fs));
        }
    }
};

State &S()
{
    static State s;   /* C++11 magic static: thread-safe first init */
    return s;
}

double now_ms()
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1000.0 + (double)ts.tv_nsec / 1e6;
}

/* Notes the first thread that reached an observing hook; logs once when another one does. Called
 * with s.mu held. */
void note_thread(State &s)
{
    pthread_t me = pthread_self();
    if (!s.owner_set) { s.owner = me; s.owner_set = 1; return; }
    if (!pthread_equal(s.owner, me) && s.foreign_calls++ == 0)
        fprintf(stderr, "[FRAMESTEP] observing hook reached from a second thread (accounted anyway)\n");
}

struct Lock {
    State &s;
    explicit Lock(State &st) : s(st) { pthread_mutex_lock(&s.mu); note_thread(s); }
    ~Lock() { pthread_mutex_unlock(&s.mu); }
};

/* The game's mode word as the setters stored it: [[TOC-0x7B94]+0x378] (0x901778 in this boot).
 * -1 when the pointer is not there. Logging only. */
int game_mode_word(ppu_context *ctx)
{
    uint32_t p = vm_read32((uint32_t)ctx->gpr[2] - 0x7B94u);
    if (p == 0) return -1;
    return (int)vm_read32(p + 0x378u);
}

void force_mode(const char *site, uint64_t *reg)
{
    State &s = S();
    int want = __atomic_load_n(&s.decision, __ATOMIC_RELAXED);
    if (want < 0) return;
    fprintf(stderr, "[FRAMESTEP] setter %s: game mode word %d -> %d\n", site,
            (int)(int32_t)*reg, want);
    *reg = (uint64_t)(int64_t)want;
}

} // namespace

extern "C" {

/* after `lwz r3,0x18(r3)` at 0x583E4 (func_000583D8, config word for r4 in {0,1,2,>=5}) */
B10_USED void gow2_midasm_Ben10ModeR3(ppu_context *ctx)
{
    if (!S().active) return;
    force_mode("func_000583D8", &ctx->gpr[3]);
}

/* after `lwz r0,0x18(r3)` at 0xB2638 (first instruction of func_000B2638) */
B10_USED void gow2_midasm_Ben10ModeR0(ppu_context *ctx)
{
    if (!S().active) return;
    force_mode("func_000B2638", &ctx->gpr[0]);
}

/* entry of the frame limiter func_000F7CF4 */
B10_USED void gow2_midasm_Ben10LimiterEnter(ppu_context *ctx)
{
    (void)ctx;
    State &s = S();
    if (!s.active) return;
    Lock lk(s);
    ben10_fs_obs_limiter(&s.obs, now_ms());
}

/* before `bl func_000B5C4C` at 0xF7FDC: r3 = the ticks the game is about to advance */
B10_USED void gow2_midasm_Ben10FrameStep(ppu_context *ctx)
{
    State &s = S();
    if (!s.active) return;
    /* vm_read32 polls the giant-lock preemption and may yield it: never call it with s.mu held
     * (a second thread blocking on s.mu while holding the giant lock would deadlock the yielder). */
    int mode_word = game_mode_word(ctx);
    uint32_t ticks = (uint32_t)ctx->gpr[3];
    Lock lk(s);
    double t = now_ms();
    double wall = 0.0, work = 0.0;
    if (ben10_fs_obs_frame_at(&s.obs, t, ticks, &wall, &work)) {
        ben10_fs_frame(&s.fs, wall, work);
        __atomic_store_n(&s.decision, ben10_fs_game_mode(&s.fs), __ATOMIC_RELAXED);
    }
    if (ben10_fs_obs_window_due(&s.obs, t)) {
        ben10_fs_obs_window_close(&s.obs, t);
        char buf[400];
        ben10_fs_obs_format(&s.obs, &s.fs, mode_word, buf, sizeof buf);
        fprintf(stderr, "%s\n", buf);
    }
}

} // extern "C"
