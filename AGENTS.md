# AGENTS.md : monorepo prosopo-gw

Consignes pour tout assistant de code (Claude Code, Cursor, Codex…) travaillant dans ce monorepo.
Les règles ci-dessous s'appliquent partout ; `core/AGENTS.md` détaille le moteur `geneweb-py`.

## 1. Contexte et structure

prosopo-gw exploite des bases généalogiques GeneWeb (`.gw`) à des fins **prosopographiques** : parsing fiable,
modèle objet (personnes, familles, événements, **organisations**), analyse de réseaux, enrichissement LLM.

```
prosopo-gw/
  run_app.sh            # lance l'app Streamlit depuis la racine
  .github/workflows/ci.yml  # CI : lint, tests core (Python 3.11-3.13), build Docker
  pyproject.toml        # workspace uv (membres : core, app/docker/geneweb-app)
  uv.lock               # lock unifié, commité
  core/                 # paquet `geneweb-py` : parser .gw, modèles, organisations, analytics, API REST, CLI
  app/                  # application Streamlit (en refonte ; pages LLM non maintenues)
    docker-compose.yml  # geneweb-server (OCaml) + geneweb-app (Streamlit)
    docker/geneweb-app/ # paquet `geneweb-app` (pyproject.toml, Dockerfile, code Streamlit, src/)
```

Hors monorepo : `geneweb-org` (fork OCaml, spécification du format natif) et `Geneweb` (V2, archivé).
L'historique de `core/` et `app/` a été importé par `git subtree` depuis les anciens dépôts, qui restent intacts.

## 2. RÈGLE D'OR : aucune donnée généalogique réelle dans Git

Ce dépôt est **PUBLIC** (code, historique et documentation lisibles par tous) et `core/` est aussi publié séparément : la règle est stricte, sans exception.

- Interdit de versionner : `*.gw`, `*.gwo`, `*.gwb/`, `*.ged`, `*.gedcom`, `*.org.json`, exports CSV/HTML de vraies bases,
  logs avec noms, et tout nom, lieu ou date de vraie personne (code, tests, docs, messages de commit).
- Les bases réelles restent **hors dépôt**, en lecture seule, dans un dossier local non versionné.
- Tests et exemples : **fixtures synthétiques uniquement** (`core/tests/fixtures/*.gw`, noms fictifs : `DUPONT Jean`, `MARTIN Pierre_Jean`…).
  Les seules exceptions du `.gitignore` racine sont ces fixtures.
- Avant tout commit : chemins explicites avec `git add` (jamais `-A` / `.`), puis `git diff --cached --name-only`.
- **Aucun `git push` ni `--force` sans accord explicite de l'utilisateur.**
- Le contexte Docker est une liste d'autorisation (`app/docker/geneweb-app/Dockerfile.dockerignore`) : ne pas l'élargir.
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
uv run --package geneweb-app streamlit run app/docker/geneweb-app/app.py   # app Streamlit (ou ./run_app.sh)
```

Extra facultatif d'analyse de réseaux : `uv sync --extra analytics` (networkx, pyvis).

## 4. Docker

Contexte de build = racine du monorepo (`app/docker-compose.yml` : `context: ..`). L'image reproduit le workspace
(`pyproject.toml` + `uv.lock` + `core/` + `app/…`), installe `geneweb-py` non éditable dans `/opt/venv`.
Toute modification de `core/` impose de reconstruire l'image.

```bash
docker compose -f app/docker-compose.yml up -d --build   # Streamlit sur http://localhost:8501
docker compose -f app/docker-compose.yml down
```

## 5. CI (GitHub Actions)

`.github/workflows/ci.yml` (setup-uv avec cache) : `uv lock --check`, ruff (check + format) et mypy sur tout `core/src/geneweb_py`,
tests `core` sur Python 3.11 / 3.12 / 3.13 avec couverture ≥ 80 %, puis build de l'image Docker (sans push).
Les anciens workflows de `geneweb-py` sont archivés, inactifs, dans `.github/legacy-workflows/`.
Le lint local équivalent : `uv run --package geneweb-py ruff check core/src core/tests --ignore E501`.

## 6. Conventions

- Langue : français pour la documentation et les échanges ; code, identifiants et messages de commit en anglais
  (`type(scope): message` : `feat`, `fix`, `docs`, `test`, `chore`). Un sujet par commit.
- Changements incrémentaux, tests verts à chaque étape ; couverture `core` ≥ 80 %, mypy strict.
- Ne pas supprimer ni écraser de fichier local non versionné sans accord.
- Décisions d'architecture documentées dans `core/doc/` ou `app/doc/`.
