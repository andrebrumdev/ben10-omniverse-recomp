# bench/ — harness de medição da carga e do áudio (Ben 10)

Reprodutível: os números dos planos em `ps3recomp/docs/superpowers/plans/2026-09-30-ben10-pipeline-opportunities.md`
saem daqui. Método: `measuring-expensive-systems` — previsões escritas ANTES da série, braços
intercalados, >= 2 corridas por braço, janelas por evento, build (rev + mtime) em cada `.meta`.

| Arquivo | Função |
|---|---|
| `run_lp.sh <tag> <profile\|clean> [ENV=..]` | uma corrida muda e sem janela, serializada por `LOCK_DIR` (mkdir atômico), recusa bateria, espera se houver jogo rodando, mata só o próprio pid. Escreve `lp_<tag>.log/.meta/.thr` em `BENCH_OUT` |
| `lp_an.py <dir> <tag>...` | análise por evento: janela da carga, % de blocos de áudio pulados, espera/retenção do giant, fps/frametime do gameplay |
| `lp_an2.py <dir> <tag>...` | CPU por thread na janela da carga (precisa do `.thr`) |
| `phases.py <dir> <tag>...` | visão grossa do áudio por fase (TITULO/CARGA/GAMEPLAY) |
| `thrmon.c` | `thrmon <pid> [ms]`: CPU por thread, prioridade e fatia de P-cores (compilado sob demanda pelo `run_lp.sh`) |
| `s9b.pad` | `PS3_PAD_SCRIPT`: título -> NEW GAME -> Training Simulation 1 (ocioso depois de 100 s) |
| `mk_combat_pad.py` / `s9b_combat.pad` | o mesmo até o nível + ciclo mover/atacar/pular de 100 s a 420 s (soak) |
| `mk_reload_pad.py` / `s9b_reload.pad` | o mesmo até o nível + taps de CROSS + ciclos de recarga do nível pelo menu de pausa (START, DOWN x4, CROSS, CROSS, LEFT, CROSS = Select Level > Training Time > YES); `test_mk_reload_pad.py` valida a gramática e o ciclo offline |
| `jcw_an.py <dir> <tag>...` | A/B do `PS3_JC_WORKERS`: fps/frametime do gameplay (t >= 130 s, draws>=100), `[JCPAR]` (jobs, tempo serial, `seg_wall_ms`), CPU por thread; uma linha por corrida |
| `s9b_diff.pad` | o `s9b.pad` com os toques de CROSS repetidos a cada 7 s ate' 300 s: com `PS3_JC_DIFF=1` o jogo roda ~5 fps e o relogio do `s9b.pad` passaria do menu antes da hora |
| `test_run_ben10_env.sh` | teste da receita de env do `run_ben10.sh` (binário falso que imprime o ambiente) |
| `test_lp_an.py` | teste do analisador com log sintético: `python3 bench/test_lp_an.py` |
| `fs_an.py <dir> <tag>... [--control tagA,tagB]` | checagem de VELOCIDADE e MARCO do passo de quadro (plano 60 fps, Tarefa 4): velocidade por janela de 30 s do gameplay, marco (`.ls` do nível) contra o controle OFF, fps médio, crash/hang |
| `test_fs_an.py` | teste do `fs_an.py` com logs sintéticos (inclui mutações: tolerância, início da janela, ticks inferidos, tolerância do marco): `python3 bench/test_fs_an.py` |

Variáveis do `run_lp.sh`: `BENCH_OUT`, `BIN`, `LOCK_DIR`, `PS3RECOMP`, `PAD_FILE`, `STOP_AFTER`
(padrão 35 s depois do `.ls` do nível), `CAP` (padrão 175 s), `EXTRA_TRACE`, `RECIPE_ENV`.
O harness tem a receita base embutida (a do `run_ben10.sh` de 2026-09-30); variáveis que o
`run_ben10.sh` ganhar depois entram por `RECIPE_ENV`/argumentos, e cada `.meta` as registra.

## Janelas por evento (nunca por relógio)

- **Carga do nível** = primeiro `open …/LoadingScreens/*.ls` com t > 55 s -> primeiro `[FPS]`
  (depois de L+1 s) com `draws>=100`. O "~80 s" antigo era o relógio do pad; a carga real tem 6-8 s.
- **Carga do hub** = primeiro `.ls` com 10 < t <= 55 s; janela de 5 s para o % de pulos.
- **% de pulos** = soma de `[AUDIO] pulados` na janela / (188 blocos/s x segundos da janela).

## Validade

- Corrida **válida** = `.ls` do nível visto **e** >= 20 s de `draws>=100` depois da carga.
  Inválida = excluída (não significa "sem efeito").
- Excluir corridas com fatia de P-cores < 0,95 (`pcore=` do `.thr`) e as tomadas com outra sessão
  compilando (o `.meta` guarda `loadavg` e os 3 maiores processos que não são o jogo).
- Só comparar corridas do mesmo regime de máquina e do mesmo binário; `sample` perturba o jogo
  (fps 26 -> 10): segundos amostrados nunca entram em fps/ms, só em fatias.
- Antes de medir: `cmake --build build-macos --target ps3recomp_runtime` no ps3recomp e
  `./build_macos.sh` no port.

## Checagem de velocidade e marco do nível (passo de quadro, `PS3_BEN10_FPS`)

O fps sozinho engana neste jogo: a lógica avança em passo fixo por quadro (ticks de 1/600 s; 20 no modo 0 de 30 Hz, 10 no
modo 1 de 60 Hz), então a velocidade do jogo é `fps x ticks / 600`. Abaixo do alvo (29,97 no modo 0, 59,94 no modo 1) o jogo
roda em câmera lenta, e no modo 1 a metade da velocidade do modo 0 para o mesmo fps. Por isso toda comparação de `PS3_BEN10_FPS`
tem dois critérios além do fps.

Corrida (uma por braço, intercaladas, >= 2 por braço e por pad, regime registrado no `.meta`):

    BIN=boot_ben10_fs4 CAP=420 STOP_AFTER=240 RECIPE_ENV="PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F" \
      PAD_FILE=bench/s9b.pad bench/run_lp.sh ioff1 clean                       # controle (PS3_BEN10_FPS desligado)
      PAD_FILE=bench/s9b.pad bench/run_lp.sh iauto1 clean PS3_BEN10_FPS=auto   # braço sob teste
    python3 bench/fs_an.py <BENCH_OUT> iauto1 iauto2 --control ioff1,ioff2

Janela de gameplay = `.ls` do nível + 20 s -> último `[FPS]`, cortada em subjanelas de 30 s. Critérios (plano, Tarefa 4):

| critério | como é medido | passa se |
|---|---|---|
| velocidade | por subjanela: média de `win_speed` do `[FRAMESTEP]` (ticks reais do jogo). Braço OFF não imprime nada: velocidade INFERIDA = `fps x 20 / 600` (20 ticks por quadro no modo 0, verificado em todos os quadros pelo log de ticks da Tarefa 1; o braço `PS3_BEN10_FPS=30` mede o mesmo valor com o observador e confere) | 1,00 +- 0,02 em TODAS as subjanelas |
| marco | `.ls` do nível (primeiro `LoadingScreens/*.ls` com t > 55 s, relógio do log) contra a média dos controles OFF | dentro de 1 s; o piso de ruído OFF contra OFF vai junto (`noise_floor_s`) |
| fps | média por segundo na janela de gameplay (não a mediana) | >= a média do controle |
| estabilidade | `[CRASH]`, `alive_at_stop`, última linha do log | sem crash, sem saída antecipada |

Leitura honesta (aprendida na Tarefa 4): a velocidade 1,00 exige que a MÁQUINA segure o período do limitador no gameplay. Com o
Training Simulation 1 a ~20 fps (regime carregado, N=1) o controle OFF também reprova (0,63-0,70), então o critério literal
é regime-limitado e a razão `speed_ratio` (braço / controle) é o número que separa defeito do hook de limite da máquina. O
marco do nível depende do ritmo das cenas do front-end contra o relógio de parede do pad: os controles OFF já divergem entre
si (`.ls` do nível em 63,3 a 77,3 s em 7 corridas OFF/30 do mesmo binário, mediana 70,3), então confira `noise_floor_s` antes de
culpar o braço. Capturas no mesmo instante de PAREDE só são comparáveis se a velocidade do jogo for a mesma: a meia velocidade
põe a cena de abertura do nível (diálogo, corrida da câmera) onde o controle já está no tutorial.

Capturas do mesmo momento: `PS3_METAL_SHOW_DUMP_EVERY=300 PS3_METAL_SHOW_DUMP_AFTER_S=100` (diagnóstico, desligado por padrão) grava
`show_f<quadro>.bmp` no diretório de saída; use um `BENCH_OUT` por braço (os nomes colidem entre braços) e corridas separadas das
de medida (a captura perturba o tempo de quadro). Pad ocioso: o momento é "`.ls` do nível + N s"; no pad de combate o estado do
jogo diverge pela razão de velocidade, então só a renderização é comparável.

## A/B do `PS3_JC_WORKERS` (job chain em N SPUs)

- Corrida de medicao: `STOP_AFTER=400 CAP=215 EXTRA_TRACE="PS3_TRACE_JC_PAR=1" RECIPE_ENV="PS3_GIANT_HANDOFF=1 PS3_VM_FAST_MASK=0x7F" bench/run_lp.sh <tag> clean PS3_JC_WORKERS=<N>`
  (janela de gameplay = t >= 130 s ate' o fim, ~85 s sem `sample`). Bracos intercalados (ABCCBA), >= 2 corridas por braco.
- NUNCA `PS3_TRACE_JOBCHAIN=1` numa corrida de medicao: imprime uma linha por job e o `[JCPAR]` deixa de contar os jobs.
  Serve para o `miss` (linha `[jobchain] stats`) e para a porta de correcao.
- Porta de correcao: `PAD_FILE=bench/s9b_diff.pad STOP_AFTER=100 CAP=420 EXTRA_TRACE="PS3_TRACE_JOBCHAIN=1" ... PS3_JC_WORKERS=<N> PS3_JC_DIFF=1`;
  passa com `div=0 atomic=0 fault=0 overflow=0` em todas as linhas `[jobchain] diff fp=...` e `miss=0`.
- Regime: o fps do braco serial varia de 14 a 20 conforme a maquina (outras sessoes compilando); so' comparar bracos da mesma janela e
  checar `load`/`top` do `.meta`. Controle de regressao: o binario antigo (`boot_ben10_arch`) e o novo com `PS3_JC_WORKERS=1` dao o mesmo
  numero na maquina quieta (20 fps, p50 48 ms, 47 mil jobs/10 s).
