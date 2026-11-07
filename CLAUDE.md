# CLAUDE.md

@AGENTS.md

Règles complètes (règle d'or sur les données réelles, workspace `uv`, Docker) dans `AGENTS.md` ; détails du moteur dans `core/AGENTS.md`.

## Commandes rapides

```bash
uv sync --all-packages --all-extras                                  # installer
uv run --package geneweb-py python -m pytest core                    # tests du core (ou: uv run --package geneweb-py pytest core)
uv run --package prosopo-gw-atelier python -m pytest atelier        # tests de l'atelier
docker compose -f docker/docker-compose.yml up -d --build            # serveur GeneWeb OCaml (référence)
```

## Rappels pour Claude Code

- Monorepo **public** : jamais de `*.gw`/`*.ged` réels, de clé d'API ni de nom de vraie personne (fixtures synthétiques uniquement).
- Pas de `git add -A` ; pas de `git push` ni `--force` sans accord explicite.
- Le paquet applicatif s'appelle `prosopo-gw-atelier` (module `prosopo_gw_atelier`) et vit dans `atelier/`.
