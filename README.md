# Ben 10 Omniverse — native macOS port by static recompilation

**Ben 10 Omniverse** (PS3, `BLUS31017`, version 01.00) running **natively on Apple Silicon**: no emulator, no JIT.
The PowerPC (PPU) and Cell SPU code is translated ahead of time into C/C++, compiled with clang for arm64 and linked
against a reimplementation of the PS3 OS and libraries. Graphics use **Metal**, cutscenes **VideoToolbox**, sound **CoreAudio**.

> This repository contains **no game code and no game assets**. You need your own legitimate copy of the game; the
> files below only describe how the build is made and how it is measured.

Sister project: [gow2-recomp](https://github.com/andrebrumdev/gow2-recomp) (God of War II HD), same engine.

## Status

| Area | State |
|---|---|
| Boot, logos, intro videos (H.264) | ✅ videos decoded by VideoToolbox |
| Title screen, front-end hub, New Game | ✅ |
| First level (Training Simulation 1): walking, dialogue, HUD | ✅ plays; later levels not verified |
| Frame rate | 🟡 the game is locked at 30 fps by its own limiter and has a 60 Hz mode of its own; on a fanless MacBook Air M5 the machine reaches 27–59 fps depending on heat and load |
| Audio | ✅ music, voices and effects; short dropouts only on some loading screens |
| Controllers | ✅ GameController (DualShock 4 / DualSense / Xbox / MFi) and keyboard |

Measured, not claimed: the per-job cost of the lifted SPU code follows the SoC clock, not the runtime; the notes in
[`notes/`](notes/) and the harness in [`bench/`](bench/) show how the numbers were taken.

## What is here

| Path | Purpose |
|---|---|
| `recomp.toml`, `functions.json`, `spu_jobs.toml` | lifter configuration: function bounds, mid-asm hooks, SPU jobs/tasks to lift |
| `host/` | host-side code linked into the binary (frame-step hooks, frame pacing policy) with unit tests |
| `bench/` | measurement harness: scripted pad input, event-window analysis, A/B scripts |
| `notes/` | engineering log: what was measured, what was refuted |
| `build_macos.sh`, `run_ben10.sh` | build and run recipes (environment variables are documented in the script header) |
| `boot_macos.cpp` | macOS entry point (guest on its own thread, window pumped on the main thread) |

## Building

The port is built by [`build_macos.sh`](build_macos.sh) against the engine's runtime library. The engine is a fork of
[sp00nznet/ps3recomp](https://github.com/sp00nznet/ps3recomp) with a macOS/Metal port and additional work on the SPU
runtime; **that fork is not public yet**, so a clean build from this repository alone is not possible today. Pieces that
apply to the upstream engine are being sent there as pull requests
([#206](https://github.com/sp00nznet/ps3recomp/pull/206), [#207](https://github.com/sp00nznet/ps3recomp/pull/207),
[#208](https://github.com/sp00nznet/ps3recomp/pull/208)).

## Notes

- Everything that is an experiment is gated by an environment variable and off by default.
- Findings are written down with the evidence that supports them; refuted hypotheses are kept in the notes.
