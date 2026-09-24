# Ben 10 Omniverse — recompilação estática PS3

Port de **Ben 10 Omniverse** (BLUS31017, disco, versão 01.00) usando o motor
[ps3recomp](https://github.com/andrebrumdev/ps3recomp), no mesmo modelo do GoW2.

No monorepo, este repositório fica em `games/ben10-omniverse/` via `git subtree`.
O checkout físico com os dados do jogo fica ao lado do `ps3recomp`
(`../ben10-omniverse-recomp`).

## Dados do jogo (nunca versionados)

```
extracted/PS3_GAME/...   conteúdo do disco (USRDIR, PARAM.SFO…)
extracted/PS3_DISC.SFB
EBOOT.BIN                SELF do disco (cópia de extracted/PS3_GAME/USRDIR)
EBOOT.ELF                ELF decriptado
```

Decriptação com a ferramenta do próprio motor (SELF de disco = tipo APP, sem licença):

```bash
clang -O2 -o ps3_unself ../ps3recomp/tools/unself/ps3_unself.c -lz
./ps3_unself EBOOT.BIN EBOOT.ELF
```

A saída foi conferida e é idêntica byte a byte ao `rpcs3 --decrypt`.

## Estado

Levantamento inicial feito (sem lift ainda). Ver [`notes/2026-09-24-survey.md`](notes/2026-09-24-survey.md).
