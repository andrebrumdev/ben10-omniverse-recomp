# Tarefa 6 do plano 60 fps: de onde vem a inflação do custo por job (diagnóstico, sem correção)

Data: 2026-10-01. Plano: `ps3recomp/docs/superpowers/plans/2026-09-30-ben10-60fps.md`. Sondas no ps3recomp `888ae250` (sobre `5ce9f15d`), port `d3189d8` + bench/build desta nota.
Identidade: binários `boot_ben10_t6` (lift `recomp_macos_fs`, -O1/-O2 como o T5; mtimes 07:28, 07:47, 08:27, 09:23 de 01/10, cada série no `.meta`), `boot_ben10_t6o3` e `boot_ben10_t6o3m5` (só os jobs SPU liftados em -O3 / -O3 -mcpu=apple-m5, via `JOB_CFLAGS`).
Evidência completa fora do git: scratchpad `fps60y/` (`diagnosis.md`, `predictions_t6.md` escrito ANTES das sondas, `table6.txt`, `runs/lp_*`).
Ferramentas novas: `bench/t6_an.py`, `bench/sample_an.py` (+ testes), `thrmon` com GHz/IPC/thermal, `run_lp.sh <tag> gs`, `JOB_CFLAGS` no `build_macos.sh`.

## Resultado

**A inflação por job não é do nosso runtime.** O trabalho por quadro é constante (ciclos do corpo dos jobs: 163-169 Mcyc por quadro, ±4 %, a N=1/3/4/5, frio ou quente); muda o **relógio** em que esses ciclos rodam e a colocação em P/E-core,
e os dois são do SoC: esta máquina é um **MacBook Air M5 sem ventoinha** (Mac17,3, 4P+6E). GHz efetivo do job medido dentro do processo (`thread_selfcounts`): 4,15 (N=1 frio) -> 3,3 (N=5 frio) -> 2,4 (N=5 com pressão térmica 2)
-> 2,1-2,2 (N=5 com pressão térmica 2 e um daemon a 170 % de CPU). O us/job acompanha 1/GHz: 173 -> 217 -> 303 -> 348 us (CPU por job). Os ajudantes do runtime somam <= ~4,5 % do tempo ocupado dos workers; o mutex global da linha de reserva
não está no caminho dos jobs dominantes (0,00 aquisições por job); o IPC é igual para k = 1..5 dentro de uma corrida. O x1,75 do T5 (N=1 -> N=5) soma o **estado térmico/de carga** (a parte maior) e o **efeito de N** (x1,12-1,26 numa máquina fria e quieta).
O mesmo binário a N=5 passa o portão G-C a frio (59,0 fps, p95 17,1-18,9 ms, 0 % de áudio pulado), fica em 56-58 fps / p95 18,6-21 ms com a máquina saturada de calor, e reproduz o T5 (49 fps, p95 24 ms, 6 % de pulos) com carga extra.

| estado | N | us/job (CPU) | GHz | IPC | fatia P | kcyc/job |
|---|---|---|---|---|---|---|
| frio | 1 | 170-172 | 4,13-4,15 | 4,36-4,44 | 0,99 | 684-697 |
| frio | 5 | 217 | 3,29 | 3,95 | 0,66 | 698 |
| quente (térmica 2) | 5 | 297-309 | 2,38-2,49 | 3,82 | 0,58-0,61 | 721-723 |
| quente + daemon a 170 % | 3 / 4 / 5 | 343-351 / 336-350 / 343-354 | 2,1-2,2 | 3,7-4,1 | 0,8 / 0,7 / 0,53-0,60 | 700-768 |

Fatias medidas: corpo do job 96,6 % do tempo ocupado dos workers a N=5 (97,2 % a N=1; uma função, `ben10_job_844e80_spu_func_000012E0`, tem 90 % dele); mem* da libc 1,8 %; sync 1,7 %; sigsetjmp 0,3 %; sonda 1 %.
Decode (FIFO): parede = CPU, 13,3-15,4 Mcyc por quadro constantes, o ms por quadro segue 1/GHz (3,45 ms a 4,18 GHz; 6,3 ms a 2,13 GHz): mesma causa, o relógio, não a giant. Com os workers nos E-cores o decode volta a 4,05 GHz.
Áudio a N=5: os pulos acompanham o hold da giant e o decode por quadro (Spearman +0,68 e +0,71 em 36 corridas), não a QoS dos workers; a classe dos workers é DEFAULT (0x15), não UI como supúnhamos.
-O3 / -mcpu=apple-m5 nos jobs: instruções por job idênticas a 0,1 % (2761 contra 2764); sem ganho, não mantido.

Maior custo removível: os **ciclos dentro dessa única função liftada**; o relógio é maior mas é do hardware. Direção: reduzir ciclos do corpo (lifter: padrões constantes de shufb, máscaras de LS, representação de ordem de bytes);
precisa de -10 % para ficar no limitador a quente e -14..-22 % no regime carregado. Medir antes a mistura dinâmica de instruções da função. Detalhes, hipóteses refutadas e limites: `diagnosis.md`.

## Limites

- A série com N=2 (e) foi contaminada por outra sessão rodando o GoW2: excluída, não há N=2 válido; N=1 quente discorda entre réplicas (193 e 252 us).
- A mistura dinâmica de instruções da função quente não foi medida (sem xctrace); `-mcpu` mais novo que apple-m1 não roda em Macs mais antigos.
- Os valores de relógio de P e E são inferidos (ciclos / CPU da thread e fatia P do processo), o relógio do cluster não é legível sem root.
