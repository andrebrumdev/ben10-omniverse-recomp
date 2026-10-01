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
| `test_run_ben10_env.sh` | teste da receita de env do `run_ben10.sh` (binário falso que imprime o ambiente) |
| `test_lp_an.py` | teste do analisador com log sintético: `python3 bench/test_lp_an.py` |

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
