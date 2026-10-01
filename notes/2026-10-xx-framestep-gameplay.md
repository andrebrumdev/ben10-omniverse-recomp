# Frame-step A' in gameplay (Task 4 of the 60 fps plan): NOT acceptable at today's machine speed

Verdict: **F1 fires. Policy M (`PS3_BEN10_FPS=auto`, the only `auto` that exists after Task 1 refuted P) runs the level at HALF the
control's game speed in every run. Route A' in its M-at-scene-boundary form must not ship as a default.** The failure is not a hook bug (k1 = 100 %, mode word 1, no crash);
it is the structure of a fixed step per frame: speed = fps x ticks / 600, so below 29.97 fps mode 1 (10 ticks) is exactly half as fast as mode 0 (20 ticks).

Build: binary `boot_ben10_fs4` (link 30/09 23:54:50, lift `recomp_macos_fs` = no-hook lift + 4 mid-asm hooks), ps3recomp 5ce9f15d, runtime lib 30/09 21:21:47
(`cmake --build`: "no work to do"), port 17fc337 + `bench/fs_an.py`. Predictions were written before the first run: `bench/out/pred_fs4.md` (not versioned; bench/out is ignored).
Harness: `bench/run_lp.sh` clean, recipe `PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F` (= run_ben10.sh), N=1 job-chain worker (default), `STOP_AFTER=240 CAP=420`,
hidden + muted, on AC, serialized by the scratchpad lock; arms interleaved, rep 2 reversed; `bench/s9b.pad` (idle after 100 s) and `bench/s9b_combat.pad` (move/attack/jump cycle).
**Regime: LOADED** (VM, WindowServer, WebKit, Safari, other sessions; loadavg 1m 1.6-3.3 across the series; CPU-weighted P-core share 0.976-0.979 in all 9 runs,
so none excluded; `cauto1` had an unrelated process (CodexBar) at 97 % CPU, kept and flagged). **fps and speed numbers are NOT comparable with other regimes**;
the verdict rests on the ratio auto/OFF and on the structure, both regime-independent in direction.

## Results (gameplay window = level .ls + 20 s -> end, seven 30 s sub-windows; speed OFF is INFERRED fps x 20/600, hook arms are the game's own ticks)

| run | arm | pad | level .ls (s) | gameplay fps avg | speed per 30 s window | mode word | crash/exit |
|---|---|---|---|---|---|---|---|
| ioff1 | OFF | idle | 72.1 | 20.3 | 0.63 0.67 0.67 0.69 0.69 0.70 0.69 | - | no |
| ioff2 | OFF | idle | 70.3 | 20.0 | 0.63 0.66 0.67 0.67 0.68 0.68 0.68 | - | no |
| iauto1 | auto | idle | 77.3 | 19.9 | 0.33 0.32 0.32 0.35 0.35 0.35 0.34 | 1 | no |
| iauto2 | auto | idle | 77.3 | 19.6 | 0.33 0.32 0.32 0.35 0.34 0.35 0.35 | 1 | no |
| coff1 | OFF | combat | 70.3 | 19.1 | 0.64 0.63 0.63 0.63 0.64 0.65 0.64 | - | no |
| coff2 | OFF | combat | 63.3 | 19.1 | 0.67 0.62 0.62 0.62 0.64 0.64 0.65 | - | no |
| cauto1 | auto | combat | 77.3 | 17.6 (CodexBar 97 %) | 0.28 0.29 0.29 0.31 0.34 0.29 0.30 | 1 | no |
| cauto2 | auto | combat | 77.3 | 19.0 | 0.34 0.31 0.33 0.31 0.33 0.33 0.31 | 1 | no |
| i30 | `30` (hook active, measured) | idle | 63.4 | 19.5 | 0.70 0.68 0.57 0.66 0.67 0.68 0.69 | 0 | no |

Pass criteria of the plan (Task 4) vs result:

- **speed 1.00 +- 0.02 in every 30 s window: FAILS in every run, control included.** OFF 0.62-0.70, auto 0.28-0.35. The control fails because the machine
  makes ~20 fps (T1: 14-24 fps) and cannot hold 29.97; the literal criterion is regime-limited. The discriminating number is **speed ratio auto/OFF = 0.50 / 0.50
  (idle) and 0.47 / 0.51 (combat)**, exactly the structural 10/20 ticks. The measured `30` arm (i30) agrees with the inferred OFF speed (0.57-0.70 at 17-20 fps),
  which supports the `fps x 20/600` inference. P(machine reaches 1.00 in gameplay at N=1) is nil in any regime measured so far (quiet N=1: 27 fps).
- **level .ls within 1 s of the OFF control: FAILS.** auto = 77.3 s in 6/6 runs (4 here + 2 screenshot runs); OFF-class runs (OFF and `30`) = 72.1, 70.3, 70.3, 63.3, 63.4, 70.35 and 77.3
  (the screenshot combat OFF run). Median OFF 70.3, so auto is +7 s later, but the OFF spread alone is 14 s, so this landmark is a weak discriminator here (the pad is on the wall clock
  and scene durations jitter in OFF); auto is deterministic at the late edge. Probable cause (not isolated): the heavy front-end scene (~209 draws, ~14 s, T3) runs at speed 0.40 in mode 1 instead of ~0.7.
- **fps avg >= OFF: strictly FAILS in 4/4 pairs, by 0.3 / 0.5 / 1.5 / 0.1 fps** (idle 20.3, 20.0 vs 19.9, 19.6; combat 19.1, 19.1 vs 17.6, 19.0). The largest gap is the run with the unrelated 97 % process.
  Not distinguishable from noise with 2 runs, but the criterion as written is not met.
- **no crash / hang / early exit: PASS** in 9 measurement runs and 4 screenshot runs (all alive at the stop, last log line ~ the cap; no `[CRASH]`, no "second thread" warning from the hooks).
- **same-moment screenshots: FAIL as stated, with a clear reason.** Idle pad, same wall moment after the level .ls (+67 s): OFF is at the tutorial popup, auto is still in the level's
  opening cutscene (the game ran at half speed), so 40-55 % of the pixels differ. Rendering itself looks right in all frames inspected (HUD, models, shaders; no artifact in the auto frames, idle and combat).
  A fair same-GAME-moment comparison needs equal game speed; not possible between these arms.

Predictions (`pred_fs4.md`): G1 (OFF 14-28 fps, speed 0.45-0.85) confirmed; G2 (auto enters the level in mode 1) confirmed 6/6; G3 (auto speed ~0.5x OFF) confirmed; G4 (fps within 1 fps)
confirmed on 3/4 pairs, the 4th explained by an outside process; G5 (landmark delta > 1 s) confirmed, OFF-vs-OFF noise floor was worse than predicted (14 s, not <= 1 s); G6 confirmed; G7 confirmed (not equal, same cause as G3).

## Why M cannot be repaired by tuning

M decides at the next call of the game's own setter (scene boundary, T1). The decision before the level is made on the title scene (59.9 fps, speed 0.998), where the machine is fast, so
the level is entered in mode 1 and stays there for the whole level: a demotion decided by the first slow gameplay frames has no setter to land on (the setter runs again only at a scene change).
The fixed policy `60` is the same case. `auto-p` (per-frame step) was refuted by T1 (the scene loop caches the step at entry).

## Consequences / what is open (nothing was shipped)

- The route A' stops here as specified ("if M also fails, record and stop"). `PS3_BEN10_FPS` stays OFF by default and is not in `run_ben10.sh`.
- Mode 1 only helps if the machine holds >= 30 fps (to match mode 0's speed) and >= 59.94 fps (to reach 1.0x) in gameplay; at N=1 loaded it is ~20, so the work that decides the user's goal is the speed of
  the machine (plan Tasks 5-8), and then a re-measure of this same A/B with `bench/fs_an.py`.
- The only design left that keeps 1.0x below 59 fps is the T1 proposal S4 (refresh the cached step in the scene loop, 12 sites incl. func_00822120) to allow mid-scene switching, or a scene-entry
  decision that knows the level is heavy. Neither was tried here. Not exercised: cutscene/pause/other levels, `60` arm in gameplay, N >= 3 workers.
- Tool: `bench/fs_an.py` + `bench/test_fs_an.py` (synthetic-log tests, 4 mutations killed: tolerance, window start, inferred ticks, landmark tolerance) are what reproduces the table.
