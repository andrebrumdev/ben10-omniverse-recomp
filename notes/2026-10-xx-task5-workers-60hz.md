# Tarefa 5 do plano 60 fps: A/B de workers no modo de 60 Hz do jogo (porta G-C)

Data: 2026-10-01 (o nome do arquivo mantém o `2026-10-xx` do plano). Plano: `ps3recomp/docs/superpowers/plans/2026-09-30-ben10-60fps.md`.
Identidade dos números: ps3recomp `5ce9f15d` (lib do runtime recompilada em 01/10 06:08:47, com o fix de nSpus `9c7c79d7`), port `83bb3a5`,
binário `boot_ben10_t5` (lift `recomp_macos_fs`, mtime 01/10 06:09:08). Máquina: Apple M5 (4 P + 6 E), 16 GB, na tomada, Docker parado antes da série.
Evidência fora do git: scratchpad `fps60x/` (`predictions_t5.md` escrito ANTES da série, `t5/runs/lp_n*.log|meta|thr|reg`, `t5_results.md`).
Ferramentas novas: `bench/t5_an.py`, `bench/t5_table.py`, `bench/test_t5_an.py`.

## Veredito

**A porta G-C REPROVA.** N=5: fps médio 48,07 (corridas 48,45 / 46,88 / 48,87), abaixo de 55; p95 do frametime 22,4 ms (22,0-23,1), acima de 18 ms.
A Tarefa 9 não se justifica com esta evidência. Os falsificadores F2 (us/job do 844e80 a N=5 = 428 us = 2,4x os 177 us do P1 e 1,75x a mediana de N=1
desta série; limite 1,45x = 257 us) e F3 (hold da giant 14,4 ms/quadro, acima de 10, sem FIFO_NOLOCK) disparam.
Próxima: **Tarefa 6 (causa da inflação do custo por job)**, depois a 8 em cima dela; a 7 só se a 6 implicar a giant.

## Medido (gameplay = `.ls` do nível + 20 s -> fim, 238-243 s por corrida; 11 corridas válidas)

| N | corridas | fps médio | p50 / p95 / p99 ms | us/job 844e80 | chain ms/q | soma de jobs ms/q | hold da giant ms/q | decode ms/q | GPU ms | áudio pulado % | velocidade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | n1a-d | 25,2 / 19,0 / 17,0 / 19,3 (mediana 19,2) | 48,6 / 52,3 / 53,2 | 229 (182-263) | 51,0 | 51,0 | 8,5 | 4,1 | 7,3 | 0,0 | 0,34 |
| 2 | n2a,b | 27,1 | 35,1 / 39,1 / 40,0 | 330 | 36,6 | 71,4 | 11,3 | 5,6 | 7,1 | 0,0 | 0,46 |
| 3 | n3a,b | 34,3 | 28,3 / 30,8 / 32,0 | 384 | 28,7 | 81,0 | 12,5 | 6,5 | 6,8 | 0,16-0,28 | 0,58 |
| 5 | n5a,b,c | **48,1** | 20,9 / **22,4** / 23,6 | 428 | 19,9 | 88,9 | 14,4 | 7,8 | 6,8 | 10,4-14,4 | 0,81 |

Cada log de N >= 2 mostra `N job workers (requested N, maxContention 6, nSpus 5)`; `[FRAMESTEP]` com `mode_word=1` em 100 % dos segundos de gameplay;
sem crash, ICALL-BAD ou LONG-WAIT; `falta=0`; swap nunca cresceu (8,73 GB -> 8,45 GB). p95/p99 são a média dos percentis por segundo do log (aproximação).

O braço N=1 discordou (25,2 contra 17,0-19,3; 48 %): replicado (n1c, n1d). n1a, a PRIMEIRA corrida da sessão, é o ponto fora (us/job 182 contra 233-263);
todos os estágios de CPU se moveram juntos (hold, decode, us/job) e a GPU não (7,2-7,4 ms), sem alerta térmico no `pmset`. Por que n1a foi rápida: não sei.
N=5 não deriva (06:22 / 06:38 / 07:04: 48,5 / 46,9 / 48,9).

## Onde vai o quadro de N=5 (20,8 ms)

O chain é o estágio crítico em TODO N (parede do chain = 96-100 % do quadro). A 5 workers: chain 19,9 ms = soma de jobs / 5 (17,8) + barreira e cauda (2,1; eficiência 0,894).
A soma de jobs cresce com N (54,8 ms a N=1 contra 88,9 a N=5): o excesso, 34 ms / 5 / 0,894 = **7,6 ms do chain (37 %)** (11 ms, 53 %, contra a n1a) é a inflação por job.
us/job do 844e80 contra a mediana de N=1 (244): x1,35 (N=2), x1,57 (N=3), x1,75 (N=5), curva suave, e já x1,35 a N=2 com fatia de P-cores 0,98, então só E-core NÃO explica
(a N=5 a fatia cai a 0,65 por construção: mais de 4 threads quentes em 4 P-cores). O decode (veThread0, não é job) infla junto (4,3 -> 7,8) e a GPU fica plana (7,3 -> 6,8):
a lentidão é de CPU e compartilhada. Giant: hold 9 -> 14,4 ms/q e espera 20 -> 36 ms/q, não é crítica (14,4 < 20,8) mas é 86 % de um quadro de 16,7 ms.
Hipóteses para a Tarefa 6, SEM discriminar aqui: contenção de ajudantes do runtime/giant, banda de memória/LLC ou frequência do SoC sob carga multi-core, derrame para E-core a N=5.

| posição | estágio | ms/q | parcela do quadro | crítico? |
|---|---|---|---|---|
| 1 | chain | 19,9 | 96 % | sim (inflação por job: 7,6 ms = 37 %; barreira+cauda 2,1 ms = 10 %) |
| 2 | giant (hold) | 14,4 | 69 % | não, mas F3 disparou e cresce com N |
| 3 | decode | 7,8 | 38 % | não (sobrepõe o chain) |
| 4 | GPU | 6,8 | 33 % | não (plana em N) |

## Teto que os dados implicam para N=5 contra o limitador de 59,94

- Hoje: 48 fps médio, p95 22,4 ms, velocidade de jogo 0,81 no modo 60 (câmera lenta). N não passa de 5 (nSpus 5).
- Para fps >= 55 (quadro <= 18,2 ms, chain <= ~17,3): soma de jobs <= ~77 ms (-13 %, ~372 us/job). Para p95 <= 18 ms (p50 ~16,5, o limitador; chain <= ~15,6): soma <= ~70 ms (-22 %, ~335 us/job).
  A cláusula do p95 é a que manda.
- Sem inflação por N (244 us): chain = 54,8 / 5 / 0,894 = 12,3 ms, quadro ~13 ms, limitado pelo limitador, média ~57-59,9. Ou seja: o limitador só é alcançável com N=5 se cerca de metade
  da inflação N=1 -> N=5 sair (ou os jobs ficarem >= 22 % mais baratos por outro caminho). Depois do chain, o hold de 14,4 ms/q (<= 69 fps sozinho) passa a limitar (F3).
- É modelo (chain = (soma/N)/eficiência) calibrado nesta série; os efeitos das Tarefas 6/7/8 NÃO foram medidos.

## Custo de áudio por N (blocos pulados no gameplay; `falta`=0 em todas)

N=1 0,0 % (4 corridas), N=2 0,0 % (2), N=3 0,16-0,28 % (2), N=5 10,4-14,4 % (3). A N=5 cerca de 1 bloco em 8: chiado audível, com fatia de P-cores 0,65. Mesmo que o gate passasse,
N=5 pediria prioridade de áudio ou reserva de núcleo antes de virar receita (o N=2 de 0,7-1,0 % do modo 0 medido antes foi em outros regimes; aqui N=2 não pula).

## Regime e exclusões

Carga no início 1,8-7,0 (inclui as threads da corrida anterior); PhysMem 14-15 GB usados, 4,7-5,6 GB de compressor, 0,14-1,1 GB livres (a pressão de memória continuou, como avisado).
No `.ls`: WindowServer 15-25 %, WebContent 6-15 %, Safari 6 %; n2b teve um Python a 42 % (meus scripts de análise). O amostrador de regime das 9 primeiras corridas usou `ps %cpu`
(média com decaimento: acusou WebContent a 213 % que o `top` não confirmou minutos depois, 12,8 % instantâneo); n5c e n1d usam `top` instantâneo e não mostram processo externo acima de 58 %.
Amostras acima de 100 % pelo `ps`: n1b 4/48, n3a 2/48, n2a 1/48, n5a 1/48, n5b 1/48. Aplicando a regra de exclusão literalmente (tirar toda corrida marcada) sobram N=5 = n5c 48,87,
N=3 = n3b 32,72, N=2 = n2b 26,62 e N=1 = n1a/c/d: veredito e ordem dos braços não mudam, e dentro de N=2/3/5 as corridas marcadas e as limpas concordam (< 10 %): mantidas e marcadas.
Fatia de P-cores: N=1 0,99, N=2 0,98, N=3 0,91-0,92, N=5 0,65-0,66 (> 4 threads quentes: cai por construção; não excluída).
Ordem: planejada N1 N3 N5 N2 | N2 N5 N3 N1; a primeira invocação do meu wrapper rodou só a n1a (erro de aspas no loop de braços), o resto rodou como planejado; depois n1c, n5c e n1d.

## Previsões contra o medido (`predictions_t5.md`)

Erradas: fps de N=2 (previ 35, deu 27,1), N=3 (44, deu 34,3), us/job a N=5 (300, deu 428), decode (5-6, deu 7,8), áudio a N=5 (6 %, deu 13,9 %), N=1 (3 de 4 corridas abaixo do intervalo).
Certas: fps de N=5 (47 -> 48,1), p95 (25 -> 22,4), hold > 10 (75 % previsto), gate falha (80 %). O modelo supôs inflação por job de 1,15 / 1,3 / 1,7; o medido é 1,35 / 1,57 / 1,75 sobre a mediana
de N=1 (1,8 / 2,1 / 2,4 sobre a n1a): o acerto de N=5 foi dois erros se cancelando (custo por job subestimado, eficiência de barreira como prevista).

## Limites

Sem a repetição do melhor braço no regime R2 (VM ligada): fora deste briefing, a VM estava desligada (Docker parado). `PS3_BEN10_FPS=60` força o modo 1 só para medir capacidade; a velocidade do `auto` não foi medida.
Percentis do frametime aproximados (o log só traz por segundo). `[FPS]` é inteiro por segundo (+-0,5 fps), então chain/quadro a N=1 dá 101-103 %. Nenhum `sample` de threads de worker (é da Tarefa 6).
