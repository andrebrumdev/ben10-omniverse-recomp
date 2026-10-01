# Frame-step hook (Task 3 of the 60 fps plan): in-boot acceptance on title + front-end

Hook design (binding result of Task 1, `2026-10-xx-framestep-audit.md`): the policy is applied at the game's own mode setters, at scene
boundaries, never mid-scene. `recomp.toml` declares 4 `[[midasm_hook]]`; bodies in `host/ben10_framestep_hook.cpp`, all no-ops without
`PS3_BEN10_FPS`.

| hook | EA | what |
|---|---|---|
| `Ben10ModeR3` | after `lwz r3,0x18(r3)` at 0x583E4 (inside func_000583D8, also its fragment func_000583E4) | replaces the mode word the setter just loaded by the policy's mode |
| `Ben10ModeR0` | after `lwz r0,0x18(r3)` at 0xB2638 (first insn of func_000B2638) | same, register r0 |
| `Ben10LimiterEnter` | entry of func_000F7CF4 | timestamp, to measure the frame's work without the limiter wait |
| `Ben10FrameStep` | before `bl func_000B5C4C` at 0xF7FDC (3 lifted copies) | observe only (r3 = the game's own ticks is never touched); feeds the policy; `[FRAMESTEP]` line once per second |

Deviation from the plan text, on purpose: the plan's step (a) called the game's setter with r3=1 from a frame-boundary hook. Task 1 showed the scene
loop caches the step at entry, so the policy is applied inside the game's own setter (register override after the config load): no guest call,
no guest memory write, no poke thread.

Lift gate (ps3recomp 5ce9f15d): the no-hook lift into a scratch dir is byte-identical to `recomp_macos/` except the `lifter-rev` comment
line; the hooked lift = unhooked + 7 hook call lines + a declaration block per chunk (chunk cuts shift; concatenated bodies equal: 864 940 260 bytes).
Hooked lift lives in `recomp_macos_fs/` (gitignored); `recomp_macos/` is kept as the backup until acceptance.

## Measurement (binary boot_ben10_fs3, built 30/09 23:20:32; ps3recomp 5ce9f15d, runtime lib 30/09 21:21:47, port 21775e3 + this commit)

Runs: `bench/run_lp.sh` clean, CAP 75 s, RECIPE_ENV `PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F`, N=1 worker, hidden + muted, AC, serialized by the
scratchpad lock; interleaved OFF / 60 / auto, 2 reps. Regime: LOADED (loadavg 1m 5.0 -> 1.6 across the series; WindowServer, WebKit, Safari, a VM and other
sessions' compiles); fps numbers are NOT comparable with other regimes. Speed = the hook's own game_s/wall_s from the game's real ticks.

Windows by event: "title plateau" = from 2 s after the end of the first contiguous block of frames with draws >= 200 (the heavy front-end scene)
to 1 s before the level `.ls` open.

| arm | setter calls (game word -> forced) | title plateau fps avg | plateau speed | k1 | heavy front-end scene (draws ~209) |
|---|---|---|---|---|---|
| OFF x2 | none, no `[FRAMESTEP]` line | 29.0 / 29.0 | (20 ticks, not logged) | - | 21.7 fps (aoff2) |
| 60 x2 | 0->1 at 0.3, 0.3, 0.5, 24.5, 70.2 s | 59.1 / 59.1 | 0.998 | 100 % (1320/1320) | 23.9 / 23.0 fps, speed 0.39-0.41 |
| auto(M) x2 | 0->0 at 0.3, 0.3, 0.5 s; 0->1 at 31.8 / 31.7 s (title), 77 s | 59.1 / 59.1 | 0.998 | 100 % | 23.7 / 23.4 fps, speed 0.40 |

Proven in-boot: the hooks reach the game (the setter's loaded word is 0 and is replaced); OFF prints nothing; 60 and auto give 59.1 fps and
game_s/wall_s 0.998 on the title plateau (the 59.94 limiter of the game's own mode 1), with k1 = 100 % (the ticks are the game's own, 10 per frame).
`auto` keeps 30 Hz for the first scene and promotes before the title (the policy M promotion matured during the 30 s of the first scene).

Not good, and not tuned away: the front-end scene with ~209 draws/frame (~14 s) runs at 21-24 fps in EVERY arm (OFF too: 20-22 fps). In mode 1 that is
game speed 0.40 (10 ticks per frame) instead of ~0.7 at mode 0 (20 ticks per frame): a scene the machine cannot run above 30 fps is HALF as fast in
60 Hz mode. M only decides at the next scene boundary, so it cannot protect that scene. Whole-window averages (t >= 45 s) are therefore 54 (60 arm) and 49
(auto arm), below the plateau 59.1. Gameplay (Task 4) is the same shape: 14-24 fps measured in T1 => speed 0.25-0.4 at step 10 unless the machine gets faster.

Not proven: OFF "byte for byte" vs a pre-hook binary (no such A/B was run; evidence is only: no output, mode word unchanged, 29 fps); behaviour in
gameplay, cutscenes, other levels; no GoW2 smoke needed (ps3recomp untouched).

Reproduce: `python3 ../ps3recomp/tools/ppu_lifter.py EBOOT.ELF --functions functions.json -o recomp_macos_fs -j 6 --config recomp.toml`,
`OUT=$PWD/boot_ben10_fs3 ./build_macos.sh recomp_macos_fs`, `bench/run_lp.sh <tag> clean [PS3_BEN10_FPS=60|auto]` with `BIN=boot_ben10_fs3 CAP=75`.

## Revisão adversarial (2026-09-30, ps3recomp 5ce9f15d, port b0fad92 + o commit de correções)

Verificado por medição:
- Reprodutibilidade do lift: o comando documentado (`mkdir -p` + `ppu_lifter.py ... --config recomp.toml`) num diretório novo reproduz
  `recomp_macos_fs/ppu_recomp_*.cpp` e `ppu_recomp.h` byte a byte (22 chunks, cmp). O lifter NÃO cria o diretório de saída (falha ao gravar
  depois de ~1,5 min): o `mkdir -p` entrou no cabeçalho do build_macos.sh.
- PS3_BEN10_FPS desligado = código do jogo idêntico: removendo as 7 linhas `gow2_midasm_Ben10*(ctx);` do lift com hooks, o corpo de todas as
  funções (12 720 404 linhas) é igual ao de `recomp_macos/` (só mudam o comentário `lifter-rev`, a declaração dos hooks e os cortes de chunk).
  Em tempo de execução: todo hook sai na primeira linha sem tocar `ctx` nem imprimir (teste `host/test_ben10_framestep_hook.cpp`, 1,3 s de quadros
  simulados, `memcmp` do `ppu_context` inteiro + stderr vazio).
- Registradores: o hook NÃO chama o setter do jogo (o desvio da Tarefa 3 acima), então não há save/restore a verificar; o que existe é uma única escrita
  (r3/r0 nos hooks de modo) e nenhuma nos hooks de observação. O teste de hook compara o contexto inteiro (GPR/FPR/CR/LR/CTR/XER) e a mutação
  "força_modo também zera o registrador seguinte" e "FrameStep escreve r3" são pegas.
- Tempo: `now_ms()` é `clock_gettime(CLOCK_MONOTONIC)` direto; `PS3_EXP_TIMESCALE` só escala `mftb`/`sys_time_*` do guest (sys_timer.c), então
  game_s/wall_s usa parede real.
- Cobertura do setter: só o caminho r4<2 e r4>=5 de func_000583D8 passa por 0x583E4; r4=2 lê `0x1C` e r4=3/4 lê `0x20` (não sobrescritos). Os três
  chamadores observados usam r4=1.

Defeitos corrigidos nesta revisão:
1. Os hooks de observação (limitador, passo de quadro) rodavam sem exclusão: nada provava que só a thread do laço de quadros os alcança. Agora
   rodam sob um mutex que nunca cobre acesso `vm_*` (o `vm_read32` pode ceder o giant lock: segurar o mutex ali daria deadlock com uma segunda
   thread) e uma segunda thread é registrada uma vez; os hooks de modo leem a decisão por um espelho atômico. (`<atomic>` conflita com o
   `<stdatomic.h>` do runtime: builtins `__atomic_*`.)
2. Os testes da política deixavam sobreviver 4 mutações: o arredondamento do acumulador P (floor em vez de round), o retorno/contabilidade de
   `ben10_fs_frame` na política M, o teto `work <= wall` do observador e a fórmula de `win_speed`. Testes novos os pegam (todas as 4 mutações agora
   falham). Mutação restante sem teste: a guarda `m_flip_allowed` (equivalente enquanto os limiares do histerese a implicam; o comentário do código diz isso).
3. Não havia teste dos hooks em si: `host/test_ben10_framestep_hook.cpp` (um processo filho por política: unset/30/60/auto).

Sanidade em execução depois das correções (binário `boot_ben10_fsrev`, link de 23:42:54, lift `recomp_macos_fs` sem alteração; ps3recomp 5ce9f15d,
lib 21:21:47; porta b0fad92 + correções não commitadas na hora da corrida; AC, hidden + muted, CAP 60 s, `bench/run_lp.sh clean`, 1 corrida por braço,
máquina carregada como antes, números de fps não comparáveis entre regimes): sem `PS3_BEN10_FPS` 0 linhas `[FRAMESTEP]`; com `60` 66 linhas,
setter 0->1, `win_fps=59.9`, `win_speed=0.998`, k1 = 100 % dos 3169 quadros, nenhum aviso de segunda thread. Não é medição de desempenho nem
substitui a Tarefa 4 (jogabilidade).
