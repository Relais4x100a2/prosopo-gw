# AGENTS.md : monorepo prosopo-gw

Consignes pour tout assistant de code (Claude Code, Cursor, Codex…) travaillant dans ce monorepo.
Les règles ci-dessous s'appliquent partout ; `core/AGENTS.md` détaille le moteur `geneweb-py`.

## 1. Contexte et structure

prosopo-gw exploite des bases généalogiques GeneWeb (`.gw`) à des fins **prosopographiques** : parsing fiable,
modèle objet (personnes, familles, événements, **organisations**), analyse de réseaux, enrichissement LLM.

```
prosopo-gw/
  .github/workflows/ci.yml  # CI : lint, tests core et atelier (Python 3.11-3.13)
  pyproject.toml        # workspace uv (membres : core, atelier)
  uv.lock               # lock unifié, commité
  core/                 # paquet `geneweb-py` : parser .gw, modèles, organisations, analytics, API REST, CLI
  atelier/              # paquet `prosopo-gw-atelier` : atelier local de nettoyage (FastAPI, en développement ; doc/design_v1.md)
  docker/               # serveur GeneWeb OCaml conteneurisé (docker-compose.yml + geneweb-server/)
```

Hors monorepo : `geneweb-org` (fork OCaml, spécification du format natif) et `Geneweb` (V2, archivé).
L'historique de `core/` a été importé par `git subtree` depuis les anciens dépôts, qui restent intacts.

## 2. RÈGLE D'OR : aucune donnée généalogique réelle dans Git

Ce dépôt est **PUBLIC** (code, historique et documentation lisibles par tous) et `core/` est aussi publié séparément : la règle est stricte, sans exception.

- Interdit de versionner : `*.gw`, `*.gwo`, `*.gwb/`, `*.ged`, `*.gedcom`, `*.org.json`, exports CSV/HTML de vraies bases,
  logs avec noms, et tout nom, lieu ou date de vraie personne (code, tests, docs, messages de commit).
- Les bases réelles restent **hors dépôt**, en lecture seule, dans un dossier local non versionné.
- Tests et exemples : **fixtures synthétiques uniquement** (`core/tests/fixtures/*.gw`, noms fictifs : `DUPONT Jean`, `MARTIN Pierre_Jean`…).
  Les seules exceptions du `.gitignore` racine sont ces fixtures.
- Avant tout commit : chemins explicites avec `git add` (jamais `-A` / `.`), puis `git diff --cached --name-only`.
- **Aucun `git push` ni `--force` sans accord explicite de l'utilisateur.**
- **Aucune étiquette `core-v*` / `atelier-v*` ni publication PyPI sans accord explicite** : une version publiée est définitive.
- Donnée réelle découverte dans un fichier suivi ou dans l'historique : s'arrêter, le signaler, ne pas la propager.

## 3. Python : workspace `uv` exclusivement

Pas de `pip install`, `poetry`, `conda` ni de nouveau `requirements.txt`. Un seul `uv.lock` à la racine ; `.venv/` local, jamais commité.
`geneweb-py` est résolu comme membre du workspace (`[tool.uv.sources] geneweb-py = { workspace = true }` à la racine) :
les membres n'ont aucun chemin relatif vers l'autre. Le workspace et le paquet `core` imposent `requires-python >= 3.11`.

```bash
uv sync --all-packages --all-extras            # tout installer
uv lock                                        # après modification d'un pyproject.toml
uv run --package geneweb-py python -m pytest core        # tests du moteur
uv run --package geneweb-py ruff check core/src core/tests
uv run --package geneweb-py mypy core/src/geneweb_py
uv run --package prosopo-gw-atelier python -m pytest atelier   # tests de l'atelier
```

Extra facultatif d'analyse de réseaux : `uv sync --extra analytics` (networkx, pyvis).

## 4. Docker

Docker ne sert plus qu'au serveur GeneWeb OCaml de référence (`docker/geneweb-server/`, `docker/docker-compose.yml`) ;
les bases locales vont dans `docker/data/` (ignoré par Git). L'atelier s'installe et se lance avec `uv`, sans conteneur.

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml down
```

## 5. CI (GitHub Actions)

`.github/workflows/ci.yml` (setup-uv avec cache) : `uv lock --check`, ruff (check + format) et mypy sur tout `core/src/geneweb_py`,
tests `core` sur Python 3.11 / 3.12 / 3.13 avec couverture ≥ 80 %. Même chaîne pour l'atelier (ruff, mypy strict,
pytest, sans seuil de couverture pour l'instant).
Les anciens workflows de `geneweb-py` sont archivés, inactifs, dans `.github/legacy-workflows/`.
Le lint local équivalent : `uv run --package geneweb-py ruff check core/src core/tests --ignore E501`.

Publication (`.github/workflows/release.yml`) : l'étiquette `core-vX.Y.Z` publie `geneweb-py`,
`atelier-vX.Y.Z` publie `prosopo-gw-atelier` (trusted publishing, environnement GitHub `pypi`
avec approbation manuelle). La version de l'étiquette doit égaler celle du `pyproject.toml`
(vérifié par le workflow) ; publier `core` avant un `atelier` qui en exige une nouvelle version.

## 6. Conventions

- Langue : français pour la documentation et les échanges ; code, identifiants et messages de commit en anglais
  (`type(scope): message` : `feat`, `fix`, `docs`, `test`, `chore`). Un sujet par commit.
- Changements incrémentaux, tests verts à chaque étape ; couverture `core` ≥ 80 %, mypy strict.
- Ne pas supprimer ni écraser de fichier local non versionné sans accord.
- Décisions d'architecture documentées dans `core/doc/` ou `atelier/doc/`.
