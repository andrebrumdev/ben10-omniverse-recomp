# Frame-step consumer audit (Task 1 of the 60 fps plan)

Date: 2026-09-30 (the file name keeps the plan's `2026-10-xx` placeholder). Plan: `ps3recomp/docs/superpowers/plans/2026-09-30-ben10-60fps.md`.
Tool: `tools/audit_framestep.py` (this commit series). Evidence not in git: scratchpad `fps60x/` (`lp/lp_S{1,2,3,5,6}.log|meta`,
`predictions_t1.md` written before the runs, `hits.json`).

## Verdict: **M**, and stricter than the plan's M

> **P (per-frame step) is refuted in-boot. M is only safe at a SCENE BOUNDARY: the step may change only through the game's own setter,
> applied before the scene loop reads it. A mid-scene switch (frame-boundary hook, or the hysteresis variant of Task 2) leaves the running scene
> loop with the old step cached.**

Evidence (all in-boot unless marked static):

1. **The scene loop caches the step at entry** (static + S3). `func_00822120` (the loop that runs title, menus and gameplay: the frame limiter is
   called from `lr=0x822290` in 100 % of the gameplay frames of S3/S5 and 99 % of S6) reads `[0x90177C]` **once at entry** into the callee-saved `r28`
   (`ppu_recomp_002.cpp:220766`) and passes `r28` as `dt` (`r4`) to `func_0051B928`/`func_0051F860` on every iteration (`:220858`, `:220868`) and as
   `r3` of `func_000B5C4C` on the iteration where the limiter is skipped (`:220873`, `lr=0x8222F8`).
   **S3 (flip experiment)**: at t=120 s the integer `[0x90177C]` was rewritten 20 -> 10 once (double and mode untouched). For the remaining
   66 s: global `g=10` in 984/984 frames, but the `r4` histogram at the entry of `func_0051B928` and `func_0051F860` stayed `{20}` (x2521 calls to
   t=183.8 s, zero calls with 10), while `func_0051F860`/`func_008059B0` (which re-read the global on every call) saw 10. Same frame = dt 20 for
   one consumer and 10 for another.
2. **The game applies its own setter exactly when it enters a scene loop** (five runs, same order): `func_000583D8(r4=1)` at `lr=0x3DC09C` at
   the first scene (1.2-4.2 s), the title (32-40 s) and the level (78-107 s; offsets vary per run), coinciding with the `.ls` loading-screen opens and with the single entry read of
   `func_00822120` (1 in title, 1 in level load). A hook that re-applies mode 1 at the first frame boundary **after** that call (Task 3 (a) as
   written) runs after the loop cached 20: the scene would run with `dt=20` (cached) while `B5C4C` gets 10 ticks (double) for its whole length.
3. **Set-time caches exist** (static; cold in the measured paths, so "not exercised"): object constructors store the step in `obj+0x5C`
   (`func_006932DC` ran 57x at boot with 20); tween setters store a per-frame increment `(to-from)/(n/step)` in `obj+0x18` (`func_0036EAAC`,
   `func_007DFF10`, `func_00091F6C`); 13 script-bound accessors convert frames<->ticks at call time (`set: field = a*step`, `get: field/step`);
   timers store `base+step` / `max(0, x-2*step)` in `obj+0xC`/`obj+4`. Anything created under one step and consumed under another is mis-scaled.
   A per-frame step (P) would mix them continuously; a scene-boundary switch only mixes what survives a scene change.

Fallback ladder of the plan (F1): P fails -> M, but M **at scene boundaries only** -> else mode 0.

## Consequences for Tasks 2-4 (binding for the implementers)

- **Hook point for Task 3**: not the frame boundary. The game's setters read the mode from the config word `[[TOC-0x5A28]]+0x18`
  (`r3+0x18`; `r3=0x400001C0` in these logs, so the word is at `0x400001D8`; `limiter.md` H2 poked `0x40000258` and lost the race -- the layout is build-dependent, so a
hook must use `r3`, never a constant):
  `func_000583D8(this, r4)` (3 calls per boot, `lr=0x3DC09C`) and `func_000B2638(this)` (2 calls at boot, `lr=0x163C1C`, `0x400B9C`) do
  `mode=[this+0x18]; [0x901778]=mode; [0x90177C]=20|10|30; [0x8B4270]=double`. A mid-asm hook at the **entry** of those two functions that writes
  `[r3+0x18]=policy_mode` makes the game itself produce mode, step and double (and apply them before the scene loop reads the step): faithful,
  no race, no poke thread, no guest call from the host. Static: the mode word `[0x901778]` is **never read** by guest code in 189-331 s
  (census, below), only written, so nothing else observes the mode.
- **Do not touch** `r3` at `0xFE55C` (constant 0, scene-exit flush) or at `0x8222F8` (the loop's cached dt, 22 frames in the S6 combat run).
  At `0xF7FDC` the ticks come from the double (`int(float(double)*600)`), already consistent with the setter outputs: **no per-frame r3/`[0x90177C]`
  override is needed in M.**
- **Task 2 policy**: `fixed30`/`fixed60` stay as written. The `auto` and the hysteresis variant can only change the mode **at the next setter
  call** (a decision per scene, using the previous scene's frame-time statistics or a fixed choice); a gameplay scene lasts minutes, so "adaptive"
  degenerates to "choose per scene". Mid-scene demotion 60 -> 30 on a slow machine is not available through the setter.
- **Possible rescue of mid-scene switching (not done, proposal "S4")**: a mid-asm hook at the top of `func_00822120`'s loop refreshing
  `r28 := [0x90177C]` (plus the 11 sibling scene loops of group G9), then the Task 4 speed/landmark check. Only worth it if the per-scene policy
  proves too coarse; the set-time caches of point 3 stay unaudited in gameplay.
- Expect `[FRMODE]` lines at the boot calls to show `mode=1` when the policy asks for 60 (`PS3_EXP_TICKLOG=1` already logs them).

## What was done

Static: a base-register tracker over the whole lift (`tools/audit_framestep.py scan`) for the three ways the game reaches the state, verified against
the ELF (TOC `0x8B5C30`): `[TOC-0x7B94]=0x901400` (struct; `+0x378` mode, `+0x37C` step), `[TOC-0x58A0]=0x90177C` (direct pointer to the step),
`[TOC-0x7B50]=0x8B4260` (`+0x10` = the double). Other TOC slots near the variable (`-0x72B0`/`-0x59E8` = 0x901780, `-0x532C` = 0x901770,
`-0x6C28`/`-0x30E8` = 0x901410, `-0x4E34` = 0x8B4260) give no access at the step offset. All 36 loads of the `-0x58A0` slot have a tracked dereference
within 100 lines (nothing escapes as a pointer). Scratch lift copy only; `recomp_macos` untouched.

In-boot: scratch lift copy = `recomp_macos` (lifted 29/09 11:08, `-O1`) + `tools/probe_ticklog.py` (`bc39316`) + one counter per site + a frame hook at the
entry of `func_000B5C4C`, all behind `PS3_EXP_TICKLOG=1` (OFF = no-op):

| run | pad | binary (mtime) | what | frames | `.ls` opens (host s) |
|---|---|---|---|---:|---|
| S1 | `bench/s9b.pad` | `boot_ben10_s9x` (30/09 22:01:24) | per-site counters | 3743 | 2.6/33.7/79.3 |
| S2 | `bench/s9b_combat.pad` | `boot_ben10_s9x` | per-site counters, combat | 4535 | 1.2/32.3/77.9 |
| S3 | `bench/s9b.pad` | `boot_ben10_s9y` (22:12:38) | counters + arg histograms + flip at 120 s | 3713 | 3.4/34.5/80.1 |
| S5 | `bench/s9b.pad` | `boot_ben10_s9r` (22:46:06) | dynamic **census** by effective address | 3981 | 4.2/35.2/80.7 |
| S6 | `bench/s9b_combat.pad` | `boot_ben10_s9r` | census, combat | 8105 | 1.7/39.8/107.0 |

Build/run provenance: ps3recomp `5ce9f15d` (runtime lib mtime 30/09 21:21:47, `ninja: no work to do`), port `bc39316`, `LIFT_OPT=-O1 HOST_OPT=-O2`,
`PS3_MUTE=1 PS3_WINDOW_HIDDEN=1`, recipe of `run_lp.sh` + `PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F` (the current `run_ben10.sh` recipe), N=1 worker,
on AC, one instance at a time under the scratchpad lock (`bench/run_lp.sh` with `LOCK_DIR`), only the own pid killed.
**Regime (loadavg 1/5/15 at the level `.ls`)**: S1 3.18/7.73/9.66; S2 5.24/6.06/8.03; S3 4.15/5.20/7.12; S5 8.54/18.14/16.91; S6 not recorded (the
harness did not flag the level `.ls` and the run ended by its 330 s cap); **P-core share** of the game (CPU-time weighted, `.thr`; whole run /
last 90 s): S1 0.936/0.951, S2 0.914/0.950, S3 0.931/0.961, S5 0.961/0.941, S6 0.782/0.983 -- below the plan's 0.95 comparison bar in several windows,
which is why only regime-independent quantities (counts, ticks, which function runs) are used; top non-game processes: `com.apple.Virtualization.VirtualMachine` ~105 % CPU (S1-S3), WindowServer, WebKit/Safari, other sessions' compiles.
The game ran at ~14-16 fps in the gameplay windows of S1-S5 and ~24 fps in S6: **fps numbers are not comparable across runs or with other
regimes and are not used here**; what is used is regime-independent (counts per frame, ticks per frame, which function runs, time model
`game_s/wall_s = fps*20/600`: S3 0.493, S5 0.549, S6 0.788 = the same fps*step/600, so the logic really is fixed-step per frame).
Gameplay window = level `.ls` + 20 s -> end (S1 90 s, S2 150 s, S3 90 s, S5 89 s, S6 206 s).

## Readers of `[0x90177C]` (static: 54 lines; the plan said "17 sites")

15 loads through `0x901400+0x37C` plus 39 through the direct pointer slot. Grouped by what they do (each group = clones included):

| # | Functions (chunk:line of the deref) | lines | What it does with the step | Executed in S1-S6 |
|---|---|---:|---|---|
| G1 | `91E64 91E78 91E90 91EA4 91EBC 91ED0 91EE8 91F00 91F14 91F2C 91F40 91F54` (`_000:113434-113528`), `91F6C` (`_000:113540`) | 13 | script-bound property accessors (consecutive OPDs `0x895E28..0x895E88`, called indirectly): `set: obj.f = a*step`, `get: obj.f/step` (fields +0x8 +0xC +0x10 +0x14 +0x30), `91F6C`: `obj+0x18 = (float)(a*step)/(float)entity+0x58` | **never** (cold) |
| G2 | `8C948` (`_000:108373`), `8C980` (`_004:562269`, its tail) | 2 | `(int)(K/(float)step+0.5)`, a frame-rate query | never |
| G3 | `36EAAC` (`_000:580002`), `7DFF10` (`_002:171913`) | 2 | tween setter: `[obj+0x18] = (to-from)/(n/step)`, a **per-frame increment cached at set time** | never |
| G4 | ctors `36F6F0` (`_000:580853`), `3791F0` (`_000:590879`), `6932DC` (`_001:509833`) | 3 | `[obj+0x5C] = step` at construction (**cache**) | `6932DC`: 57x boot, 2x title, 2x level load, **0 in gameplay**; the other two never |
| G5 | `3797E8 379840 379898` (`_000:591308/591330/591350`) | 3 | `[obj+0xC] = base + step` (table value / `f2i(..)`) | `379898`: 125x boot, 2+2 later, 0 in gameplay |
| G6 | `41C7E4` (`_001:121780`), `7D8E18` (`_004:387362`) | 2 | `[obj+4] = max(0, x - 2*step)` | `7D8E18`: 4 title, 14 level load, 1/7/0/1/22 in gameplay (S1/S2/S3/S5/S6) |
| G7 | `7FF9C4` (`_004:404184`) | 1 | `n = int(f*K)/step` (ticks -> frames) | never |
| G8 | `51F860` (`_001:258522`), `8059B0` (`_002:197148`), copies `51F8C4`, `51F8CC` (`_010:322936/323424`) | 4 | **per-call re-read**: `n = round(step*timeScale)` vs a threshold (dt scaling) | `51F860`/`8059B0`: **60-100 % of the frames** of title, load and gameplay, 1-2 (up to 16 in a spike) per frame; the two copies never |
| G9 | scene loops `81D290 81D6B8 81DAF0 81DF68 81E178 81E480 81E680 81E8A0 8214B8 821F18 822120` (`_002:216895-220766`) | 11 | `dt = *step` handed to `51B928/51F860/504168` as `r4` (and to `B5C4C` in `822120`); read **once at entry** into a callee-saved register | `822120`: 1 title + 1 level (the gameplay loop); `81E8A0`: 2 per phase; `81E178`: 1; the rest never |
| G10 | `5202A8` (`_001:259114`) + 8 fragment copies (`_010:326780..328328`) | 9 | `r31 = *step` once at entry, passed as `r4` (dt) later | never |
| G11 | `51EB74` (`_004:76593/76596/76860/76866`) | 4 | `func_0033495C(step,0,0,0)` x4 (init) | boot only (5+5+4+4, 1+1 in title) |

Census (S5, S6; counts every `vm_read32` of EA 0x90177C by `__func__`): exactly the same executed functions **plus one the static scan cannot see**:
`func_0081E908`, a clone of the loading-screen loop (limiter caller `0x81EA6C`) that re-reads the step **per iteration** (boot 136 frames, title 38,
level load 95, S6: 320/60/104), **0 in gameplay**. In the gameplay windows the guest code that reads the step is only `51F860`, `8059B0` (per frame) and
`7D8E18` (rare). **42 of the 54 static lines never ran in 5 runs (incl. combat)**: that part is "not exercised", not "safe".

Writers (not consumers): the three equivalent setters `func_00058358(mode)`, `func_000583D8(this,r4)`, `func_000B2638(this)` and their switch fragments
(`58390 583A8 583C0 583E4 583E8 583F8 58418 58438 58458`, `B2674 B268C B26A4`) write mode, step and double; executed only at boot and at the
three scene entries.

## The double `0x8B4270` (`+0x10` of `0x8B4260`)

Read only by the frame limiter family, in 5 lines of 3 fragments: `func_000F7CF4` (`_000:201561` wait target `int(float(d)*1e6)`; `:201651` ticks
`int(float(d)*600)`), `func_000F7D38` (`_005:76373`, `:76463`) and `func_000F7EE0` (`_005:76561`, **missed by the base tracker**, found by the
textual pass). Census: per frame `F7CF4` reads it twice in gameplay; in boot/title/level load the ticks read is done by `F7EE0` (99 %/78-87 %/32-35 %).
Written only by the setters above.

## The three callers of `func_000B5C4C` (the logic advance, `r3` = ticks of 1/600 s)

| call site (lr) | `r3` | when | verdict |
|---|---|---|---|
| `0xF7FDC` (`0xF7FE0`), 3 clones | `int(double*600)` = 20 | every frame (3742/3743 in S1; 20 in every frame of every run) | the frame advance |
| `0xFE55C` (`0xFE560`) | **constant 0** | **once per run**, at the title -> level scene exit (S2: t=77.83 s, same instant as the setter call and the level `.ls`); the tail of `func_000FE39C`, a flush called by `func_000FE5B4` (`lr=0xFE5C8`) when `func_00822120` leaves its loop, and from `0x8223A0` | **not a loop, not gameplay**: a one-shot scene-exit flush; must never be overridden (0 ticks) |
| `0x8222F8` | `r28` = the loop's entry-cached step (20) | inside `func_00822120`, on the iteration that skips the limiter: **0 in the idle runs (S1/S3/S5), 3 in S2, 22 in S6** (combat; in S6 each in a frame whose previous limiter caller was `0x2AEC14`, a nested wait loop; the S2 events coincide with `open Sounds/405EC878A06258E8.str`) | the loop's cached dt reaches `B5C4C` here |

## Predictions vs results

Written before the runs in `predictions_t1.md` (scratchpad). P1 FE55C not a frame loop: confirmed (1 call per run, r3=0). P2 0x8222F8 modal loop active
in loading screens only: **refuted** (it is the gameplay scene loop, rare, combat-dependent; 0 in loading screens). P3 accessors < 30 % of frames: **refuted
by an even colder reality** (0 hits in 5 runs). P4 per-frame update consumers: partly (only `51F860`/`8059B0`; the loop bodies of G9/G10 never ran).
P5 constructors boot-only: confirmed. P6 setters at boot and scene changes only: confirmed (S1: 2.6/33.7/79.3 s). P7 ticks always 20 (0 once): confirmed in all five
runs. P8-P11 (S3): confirmed (entry-cached dt; global stays 10; no crash/hang in 66 s; gameplay limiter caller `0x822290`). C1-C4 (census): confirmed,
C2 found `func_0081E908`, C4 stronger than predicted (no guest reader of the mode word at all). Verdict prior M (>= 60 %): confirmed and sharpened.

## Not proven / limits

- **Gameplay coverage**: Training Simulation 1 only (idle in S1/S3/S5; mover/atacar/pular in S2/S6). Cutscenes, pause menu, other levels, loading of other
  scenes and all of G1/G3/G7/G9/G10 are unexercised. M's scene-boundary restriction is a *necessary* condition shown in-boot; its sufficiency (the set-time caches
  of point 3 behave at 60 Hz) is untested: Task 4 must check it (speed + landmark + the same combat moment).
- **What `dt`/step actually drive** is shown by dataflow (arguments), not by RE of `51B928`/`51F860` bodies: that the logic integrates with `dt` is an inference.
- The static scan is a **floor** (base register tracked inside one function; clones receiving the base from another fragment escape: `func_0081E908`,
  `func_000F7EE0`); indexed reads `(rA+rB)` on bases near the variable are unclassified. The census closes this for executed paths only.
- Whether the hysteresis variant of M would also work with a refreshed loop `r28` ("S4") is untested.
- Nothing here was measured on a quiet machine; irrelevant for counts but the fps statements of the plan (R1/R2) are not touched by this audit.

## Reproduce

```
python3 tools/audit_framestep.py scan recomp_macos                  # static sites (+#EXTRA clones of the double)
python3 tools/audit_framestep.py instrument recomp_macos <dir>/lift # counters; writes <dir>/lift_sites.txt
OUT=$PWD/boot_ben10_s9x ./build_macos.sh <dir>/lift
LOCK_DIR=<lock> BENCH_OUT=<out> BIN=boot_ben10_s9x RECIPE_ENV="PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F" \
  bash bench/run_lp.sh S1 clean PS3_EXP_TICKLOG=1 [PS3_S9X_FLIP_AT_S=120]
python3 tools/audit_framestep.py analyze <out>/lp_S1.log --map <dir>/lift_sites.txt
python3 tools/audit_framestep.py census recomp_macos <dir>/census   # dynamic census by effective address (full rebuild)
python3 tools/audit_framestep.py analyze-census <out>/lp_S5.log
```
