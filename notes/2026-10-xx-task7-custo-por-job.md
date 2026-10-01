# Tarefa 7 do plano 60 fps: menos ciclos por job SPU liftado (e o que isso fez com fps e áudio)

Data: 2026-10-01. Plano: `ps3recomp/docs/superpowers/plans/2026-10-01-ben10-jobcost-and-audio.md` (filho de `2026-09-30-ben10-60fps.md`, Tarefas 5/6 -> G-C reprovado, causa = relógio do SoC; alavanca que sobrou = ciclos por job).
Código: ps3recomp `792f1556` (SPU_FMA_ISA_GATE), `4d2440f1` (shufb/rotações sem rev32), `22cdad64` (fcgt/fceq/mpy*/xshw/csflt em NEON); porta `1d8d0d0` (jobs liftados com `SPU_FMA_ISA_GATE=0`), `40f7888` (`bench/cov_an.py`), `b9280e8` (run_ben10.sh volta a exportar HANDOFF/FAST_MASK/JC_WORKERS=2, que o 31dfcec tinha levado junto).
Binários (todos `boot_ben10_t7*`, apagados ao fim): `t7base` (runtime 509688cf = 4ba529dc + plano, jobs COM o gate; é o controle pós-merge), `t7t2`, `t7t3`, `t7t4` (= final), `t7cov` (cobertura). Cada corrida registra rev do ps3recomp, mtime da lib e do binário no `.meta`; as libs usadas foram copiadas para o scratchpad (`fps60y/t7/libs/`) para o controle não mudar sob outra sessão.
Evidência fora do git: scratchpad `fps60y/t7/` (`pred_t7_*.md` escritos ANTES de cada medição, `base.md`, `t1.md`..`t5.md`, `table_*.txt`, `runs/lp_*`, `cov/`).
Ferramentas: `bench/cov_an.py` (+ teste), harness `run_arms7.sh` e `table7.py` no scratchpad (regime por corrida: carga, top-3 de CPU não-jogo, GHz, fatia P).

## Resultado em uma linha
Os ciclos do corpo de `844E80` por job caíram **0,54-0,59x** (instruções 0,57x) com três mudanças no codegen/helpers do SPU, bit-idênticas ao `_ref` e ao interpretador (JC_DIFF 0 divergências); a N=2 (a receita) o jogo foi de ~32 fps para 50 fps com a máquina quente e para **58,8 fps / p95 17,4 ms / 0,00 % de áudio pulado** com ela fresca e quieta. O portão do plano (N=5, máquina quieta: fps >= 55, p95 <= 18, áudio < 1 %, 132 Mcyc/quadro) passa numa corrida quieta de N=5 (g5b) e reprova em duas outras corridas marcadas quietas do t7t3 (áudio 2,9 % e 11 %; p95 18,6 ms): **a aceitação a N=5 não é confiável, o áudio a N >= 4 é função do regime, e a receita fica em `PS3_JC_WORKERS=2`**.

## A cadeia (844E80, regime-independente; N=1 salvo indicação; instruções e ciclos por job em milhares)
| etapa | kins/job | kcyc/job | vs etapa anterior | Mcyc/quadro N=1 / N=5 |
|---|---|---|---|---|
| controle pós-merge (t7base) | 2 944 | 680 | - | 161 / 165 |
| 2. gate do FMA_ISA fora dos jobs (t7t2) | 2 589 | 548 | 0,880x / 0,806x | 127 / 141 |
| 3. shufb e rot/shl/shr de bytes sem rev32 (t7t3) | 2 038 | 416 | 0,787x / 0,758x | 92 / 103 |
| 4. fcgt/fceq/mpy*/xshw/csflt em NEON (t7t4) | 1 678 | 366-399 | 0,847x / 0,88-0,91x | 89 (N=2: 85) / ~97 |
Cumulativo: instruções 0,57x, ciclos 0,54-0,59x, Mcyc/quadro N=5 165 -> 97 (-41 %; alvo do plano <= 132).
- **Causa A** (gate): um call frio por op float dentro do laço `loc_000012E0` (`getenv` + `spu_f2/f3_isa`) faz o clang tratar todo `ctx->gpr[]` como clobberado a cada merge e recarregar/guardar o arquivo de registradores (363 loads/stores de ctx por iteração -> 3). O jogo de 1608 -> 1340 instruções estáticas no caminho quente; dinamicamente -12 % de instruções e -19 % de ciclos.
- **Causa B** (rev32): `spu_shufb` NEON fazia 4 `vrev32q_u8` por chamada; o byte do host h É o byte SPU h^3, então `tbl2({a,b}, (sel&0x9F)^3) | tbl1(K, sel>>5)` dá os mesmos bits em 6 operações. -21 % de instruções, -24 % de ciclos.
- **Cobertura (Tarefa 1)**: o laço executa **2 059 iterações por job** (o plano supunha ~1 600), 185 instruções SPU por iteração, 99,8 % das instruções SPU do job; shufb 23,2 %, rotqby 6,5 %, float 21 %, mem 9,7 %; 844E80 = 88,8 % das instruções SPU executadas nas quatro unidades liftadas. O modelo (soma de contagem x custo do corpo do op) explicou 92 % das instruções medidas.
- `gb` não foi convertido (o clang já emite 7 instruções; a versão NEON tem a mesma contagem).

## Correção
- JC_DIFF=1 (N=5, `s9b_diff.pad`, 60 s após o nível): t7t2, t7t3 e t7t4, 4 fingerprints cada, `div=0 atomic=0 fault=0` (844E80: 276 313 / 283 687 / 235 905 jobs comparados). O JC_DIFF é cego a mudança de helper (o interpretador usa os mesmos helpers), então a prova dos helpers é `runtime/spu/tests/test_spu_simd_diff.c`: 59,2 M comparações, 0 divergências duras, varredura exaustiva do byte seletor do shufb em todas as posições (também com dados aleatórios), contagens 0-31 de shl/rot/shr, csflt para os 256 `i8` contra todas as palavras especiais; 9 mutantes (limites, xor 2, máscara, shifts, vcge, ushr) reprovam.
- `PS3_SPU_FMA_ISA=1` com os jobs sem o gate: o registro gerado recusa registrar (`[spu_jobs] PS3_SPU_FMA_ISA set: ... -> all interpreted`) e os 4 binários rodam no interpretador (`[jobchain] MISS ... interpreted`). `spu_fma_precision` off/on passam.
- Build padrão idêntico byte a byte (otool -tV) para `test_spu_simd_diff.o`, uma unidade SPU do GoW2 e o job 844E80 com o header do Task 2; todos os 204 membros da lib são idênticos (cmp).
- GoW2 (header compartilhado): smoke de menu (`g2menu.sh`, 2 corridas por binário: controle Task 2, Task 3, Task 4, cada um linkado com a lib e os headers da sua etapa): todas chegam ao menu (draws 228, 59-61 fps), 0 ICALL-BAD/SIGSEGV/SIGBUS/assert. Não rodei a corrida de gameplay de GoW2 com save (o save do usuário não entra em teste automático): **não exercitado**. x86-64: o ramo SSSE3 não foi tocado; o teste x86 compila mas não roda aqui (sem Rosetta): **não exercitado**.
- `runtime/spu/tests/run_tests.sh`: 11 passam / 12 falham, as MESMAS 12 do HEAD 509688cf (erros de link `_ps3_atomic_line_lock`/`_spu_irq_trace_on`/`_cellSpursEventFlagSet`, preexistentes desde o 888ae250).

## Portões e retratações (honestos)
- Portão da Tarefa 2 (`kins <= 0,85x`): **FALHOU por 3 pontos (0,880x)**; `kcyc <= 0,90x` passou (0,806x). A estimativa estática (0,833x) era otimista: a contagem dinâmica removeu 65 % do delta estático. Mantive a mudança (o que importa é ciclos) e calibrei as previsões seguintes.
- O plano supunha ~1 600 iterações/job: medido 2 059. A premissa do arnês "PASS_MERGE/GPU_DESWIZZLE estavam OFF antes do merge" é **falsa para os dois do Metal** (o log do T6 já imprime `pass-merge=1 gpu-deswizzle=1`); a previsão "decode cai com o merge" foi refutada (decode 13,4-14,2 Mcyc/quadro = T6). Para SPU1/SPU6 não há marcador no log.
- Minha previsão "ciclos caem menos que instruções" (Tarefa 3) foi refutada (0,758x ciclos < 0,787x instruções).
- Mcyc/quadro depende do conteúdo da janela (156-172 no mesmo binário): comparar por job (kins/kcyc) ou na mesma janela.
- Um erro meu na leitura do log de áudio (diferença de `pulados` cumulativo; `pulados` é por segundo) deu 0 % no primeiro cálculo do soak; corrigido pelo `t5_an` (1,63 % no soak t7t3 carregado, 0,51 % no final).
- run_ben10.sh do 31dfcec tinha perdido HANDOFF/FAST_MASK/JC_WORKERS=2 (o launcher rodava serial): restaurado em `b9280e8`; `bench/test_run_ben10_env.sh` voltou a 11/11.

## Série de aceitação (binário final t7t4 contra t7base; PS3_BEN10_FPS=60; s9b.pad; janela = .ls do nível + 20 s -> fim)
**A máquina ficou compartilhada com outras sessões** (loadavg 3-40, clang++/xcodebuild/chrome-headless a 100-200 %): das 97 corridas desta tarefa só 35 são `Q` e, na série de aceitação do binário final (37 corridas), só 5 (r1a, r1b, g2b, g3b, g5b) (mediana do top-3 de CPU não-jogo <= 45 % e loadavg1 <= 8); o resto é `L` e entra como evidência de "máquina carregada", não de aceitação. Uma máquina fria de verdade (job a 4 GHz) não foi alcançável: as corridas `Q` mais frescas têm 3,2-3,4 GHz.
Corridas Q do binário final: (fps / p95 ms / áudio pulado % / speed / GHz do job / us/job 844E80 / Mcyc/quadro)
- N=2: 58,8 / 17,4 / 0,00 / 0,99 / 3,37 / 123 / 83 (g2b); 56,7 / 19,9 / 0,00 / 0,96 / 3,41 / 124 / 84 (cl2a, já com o run_lp.sh sem as variáveis promovidas); quente: 48,0 / 25,1 / 1,55 / 0,81 / 2,43 / 178 / 85 (r1b)
- N=3: 59,0 / 17,2 / 0,00 / 1,00 / 3,24 / 138 / 89 (g3b); 59,0 / 17,2 / 0,06 / 1,00 / 3,14 / 142 / 77 (cl3a); 58,5 / 17,8 / 0,38 / 0,99 / 3,22 / 141 / 87 (r1a)
- N=5: 58,9 / 17,6 / 0,27 / 0,99 / 2,97 / 166 / 97 (g5b); (carga 32 %) 59,1 / 17,2 / 0,35 / 1,00 / 2,69 / 174 / 94 (r3d)
- N=4: nenhuma corrida Q (todas L: 41-58 fps, 7-16 % de áudio pulado).
- controle t7base: N=5 Q 52,9 / 21,3 / 3,9 / 0,89 / 2,22 GHz; N=2 Q 37,4 / 30,2 / 0,11 / 0,63 / 3,16 GHz (163 Mcyc/quadro).
Corridas L (máquina carregada e quente, GHz 2,0-2,5): N=5 fix 45-59 fps, áudio 0,3-15 %; N=4 fix 42-58 fps, áudio 7-16 %; N=3 fix 50-55 fps, áudio 5-11 %; N=2 fix 30-50 fps, áudio 0,4-4,2 %; controle N=5 15-51 fps, áudio 4-12 %.
Critérios do plano a N=5 na corrida quieta g5b: Mcyc/quadro 97 <= 132 OK; us/job (844E80) 166 <= ~335 OK (todas as corridas, até as L: 166-299); fps 58,9 >= 55 OK; p95 17,6 <= 18 OK; áudio 0,27 % < 1 % OK; speed 0,99 OK; JC_DIFF 0 OK. Mas o N=5 em máquina carregada pula 10-15 % dos blocos, e duas corridas N=5 do t7t3 marcadas Q (n5a, n5b, 2,6 GHz) deram 2,9 % e 11 %: o critério de áudio a N=5 passa numa de três corridas Q (g5b 0,27 %), portanto NÃO está provado.
Soak de 600 s (final, N=2, `s9b_reload.pad`, loadavg até 12): 631 s, 3 aberturas de nível (2 recargas), nenhum ICALL-BAD/LONG-WAIT/abort, intervalo máximo entre `[FPS]` 1,07 s, 53,6 fps de média (mín. 41), áudio 0,51 % pulado (512 blocos em 538 s), mas speed 0,90 (não 1,00 +- 0,02: N=2 não sustenta 60 Hz com a máquina quente). O soak do t7t3 (N=2, 3 x clang++ a 98 %) deu 40,4 fps e 1,63 %.
## Decisão da receita
Regra declarada antes (pred_t7_5.md): o menor N em {3,4,5} que passe tudo em AMBOS os regimes; senão fica 2. Nenhum passa o áudio na máquina quente/carregada (N=3: 5-11 %, N=4: 7-16 %, N=5: 10-15 %); N=2 mantém o áudio (0-1,6 %, uma corrida 4,2 %) e é o único que não degrada o som. **`PS3_JC_WORKERS=2` fica.** Para quem quiser mais fps em troca de áudio: `./run_ben10.sh PS3_JC_WORKERS=3` (a máquina fresca dá 59 fps com áudio limpo) ou `=4`.

## O que falta e a próxima hipótese
N=2 quente fica em 41-50 fps: a cadeia dura 19-23 ms por quadro a ~2,4 GHz e 60 fps pede <= 15,6 ms, ou seja, ~66 Mcyc de jobs por quadro (hoje 85). As alavancas medidas que sobram: (a) mais ciclos por job (o que resta são `rotqby`/`shufb` ainda ~45 % do corpo, `frest` 29 ops, `chd/chx` 19-20 ops, `gb`, loads/stores com troca de byte); (b) o áudio a N >= 4 pula por competição de núcleos (fatia P 0,5-0,6) com o decode sob o giant lock (hold 12-14 ms/quadro): Tarefa 7 do plano pai (`PS3_GCM_FIFO_NOLOCK=1 PS3_RSX_DRAIN=1`) e liftar a task SCREAM/libmixer interpretada; (c) rota B (interpolação de quadros) se a máquina quente for o alvo.
