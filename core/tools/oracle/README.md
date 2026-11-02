# Oracle GeneWeb

Compare notre lecture d'un `.gw` à ce que le GeneWeb officiel (tag `v7.1.0-beta2`) en retient.

```
base.gw ──filter.py──▶ in.gw ──gwc──▶ base.gwb ──gwu──▶ rt.gw
                                                          │
geneweb-py ◀── parse(base.gw) ── compare.py ── parse(rt.gw) ◀┘
```

## Utilisation

```bash
docker build -t geneweb-oracle:7.1.0-beta2 core/tools/oracle        # une fois
core/tools/oracle/run.sh "$GENEWEB_REAL_BASE" "$HOME/oracle_out/big"
uv run --package geneweb-py python core/tools/oracle/compare.py "$GENEWEB_REAL_BASE" "$HOME/oracle_out/big/rt.gw" [--stream] [--examples]
```

- `GENEWEB_REAL_BASE` : chemin absolu d'une base réelle, hors dépôt, en lecture seule.
- Le dossier de sortie doit être hors du dépôt : `run.sh` refuse sinon.
- L'image installe le binaire officiel du tag (pas de compilation). Les sources du même tag font foi pour les règles.
- GeneWeb 7.0 est exclu : il refuse les bases exportées de Geneanet.

**Aucune sortie n'est à versionner.** `compare.py` n'imprime que des comptages et des exemples masqués
(lettres → `a`, chiffres → `9`).
