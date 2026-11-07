# Prosopo-gw-Atelier v1 : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Construire un outil local (`uv tool install`) qui charge un `.gw`, regroupe les
écritures de lieu, les fait valider par cluster, retient les décisions dans un référentiel
personnel réutilisable et exporte un pivot (tables de `core` + `lieux`).

**Architecture :** Nouveau membre du workspace `atelier/` (paquet `prosopo-gw-atelier`, module
`prosopo_gw_atelier`) qui dépend de `geneweb-py`. Un moteur Python pur (collecte, décomposition,
regroupement, référentiel SQLite, export pivot) est servi par une API FastAPI locale
(127.0.0.1) et une interface HTML/JS sans framework. `app/` est retiré ; le conteneur GeneWeb
OCaml est déplacé.

**Tech Stack :** Python ≥ 3.11, `geneweb-py`, FastAPI + uvicorn, `sqlite3`, `platformdirs`,
`difflib` (stdlib), Bootstrap + Tabulator recopiés de `core`, pytest + `TestClient`, ruff, mypy
strict.

**Spec :** `docs/superpowers/specs/2026-11-07-prosopo-gw-atelier-design.md` (commit 3a1f681).
Les § cités ci-dessous renvoient à ce document. La tâche 3 le déplace dans
`atelier/doc/design_v1.md`.

## Global Constraints

- Dépôt PUBLIC : aucun `.gw` réel, aucun nom de personne réelle, aucun référentiel personnel réel
  versionné. Fixtures synthétiques (`DUPONT Jean`, `MARTIN Pierre_Jean`…). Les noms de **communes**
  réelles sont permis dans les tests (§ 4).
- `uv` exclusivement ; `uv lock` après toute modification d'un `pyproject.toml` ; `uv lock --check`
  doit passer.
- `requires-python = ">=3.11"` pour `core` et l'atelier.
- L'atelier **n'ajoute rien** à la CLI ni à la webapp de `core` ; il n'en recopie pas la logique
  (§ 4). Interfaces de `core` utilisées : `geneweb_py.GeneWebParser().parse_file(path)`,
  `geneweb_py.formats.tables.build_base_tables / Table / TableSpec / Column`,
  `geneweb_py.formats.table_writers.table_to_csv / tables_to_json / tables_to_sqlite /
  dictionary_table`, `geneweb_py.core.place.parse_place`.
- Le serveur n'écoute que sur `127.0.0.1` (§ 3).
- Rien n'est appliqué sans validation humaine, sauf une décision déjà prise (§ 3, § 6.3).
- Texte d'interface en français ; code, identifiants, clés JSON de l'API et messages de commit en
  anglais (`type(scope): message`).
- `git add` avec chemins explicites, puis `git diff --cached --name-only` ; ni `push` ni `--force`
  sans accord.
- Mention des sources dans tout export : « Source : INSEE, Code officiel géographique
  <millésime> ; La Poste, Base officielle des codes postaux <millésime> — Licence Ouverte 2.0 ».
- Lint, format, mypy et tests de l'atelier verts à la fin de chaque tâche :
  `uv run --package prosopo-gw-atelier ruff check atelier/src atelier/tests`,
  `uv run --package prosopo-gw-atelier mypy atelier/src/prosopo_gw_atelier`,
  `uv run --package prosopo-gw-atelier python -m pytest atelier`.

## Review Focus

1. **Base sans aucun lieu, ou lieux tous vides** : la file affiche « Aucun lieu à traiter » et
   l'export fonctionne (tables de `core` + `lieux` vide). Test : tâche 11.
2. **Écritures contenant `/`, `?`, `#`, guillemets ou espaces multiples** : elles ne passent jamais
   dans un chemin d'URL (corps JSON ou paramètre de requête encodé) et reviennent intactes. Test :
   tâche 11.
3. **Fichier du référentiel absent, ou deux instances ouvertes sur le même référentiel** : création
   à la volée ; SQLite en WAL avec `busy_timeout`, une seconde instance lit et écrit sans
   « database is locked ». Test : tâche 7.
4. **Grosse base (20 000 écritures distinctes)** : le regroupement ne compare pas toutes les paires ;
   il termine en moins de 10 s. Test : tâche 6.
5. **Import d'un fichier de référentiel d'un autre format ou d'une autre version** : refus avec
   un message clair, rien n'est écrit. Test : tâche 9.

---

## Lot A : préparer le dépôt

### Task 1 : aligner `core` sur Python 3.11

**Files :**
- Modify : `core/pyproject.toml` (`requires-python`, classifiers, `[tool.ruff] target-version`)
- Modify : `core/AGENTS.md` (§ « Python ≥ 3.8 » et la consigne « syntaxe compat 3.8 »), `AGENTS.md` § 3
- Modify : tout `core/src`, `core/tests`, `core/tools` touché par `ruff --fix` (commit mécanique séparé)

- [ ] **Step 1 :** `requires-python = ">=3.11"`, classifiers 3.11 / 3.12 / 3.13 seulement,
  `target-version = "py311"`. Retirer des docs la consigne « typing.* compat 3.8 ».
- [ ] **Step 2 :** `uv lock`, puis `uv run --package geneweb-py ruff check core/src core/tests core/tools --ignore E501` :
  attendu, des erreurs `UP` (`UP006`, `UP007`, `UP035`…).
- [ ] **Step 3 :** commit 1 (métadonnées + docs) : `chore(core): require Python 3.11`.
- [ ] **Step 4 :** `ruff check --select UP --fix` puis `ruff format` sur les mêmes chemins.
- [ ] **Step 5 :** vérifier : ruff (check + format --check) propre, `mypy core/src/geneweb_py`
  0 erreur, `pytest core` vert avec couverture ≥ 80 %.
- [ ] **Step 6 :** commit 2, purement mécanique : `style(core): modernize typing syntax for Python 3.11`.

### Task 2 : déplacer le conteneur GeneWeb OCaml

**Files :**
- Move : `app/docker/geneweb-server/` → `docker/geneweb-server/` (`git mv`)
- Create : `docker/docker-compose.yml` (service `geneweb-server` seul, repris de
  `app/docker-compose.yml` : ports 2316/2317, volumes, healthcheck, réseau)
- Modify : `.gitignore` (règles `data/…` qui suivent : vérifier avec `git check-ignore -v`)
- Modify : `core/doc/organizations_candidates_design.md` (référence au conteneur)

- [ ] **Step 1 :** `git mv`, écrire le compose réduit ; volumes relatifs à `docker/`
  (`${GENEWEB_BASES_HOST_DIR:-./data/geneweb_bases}`, `./data/geneweb_config`).
- [ ] **Step 2 :** `docker compose -f docker/docker-compose.yml config` : sortie sans erreur.
  `git check-ignore -v docker/data/geneweb_bases/x.gw` : ignoré.
- [ ] **Step 3 :** commit `chore(docker): move the GeneWeb server container out of app/`.

### Task 3 : squelette de l'atelier et retrait d'`app/`

**Files :**
- Create : `atelier/pyproject.toml`, `atelier/README.md`, `atelier/src/prosopo_gw_atelier/__init__.py`,
  `atelier/src/prosopo_gw_atelier/py.typed`, `atelier/tests/test_smoke.py`
- Move : `docs/superpowers/specs/2026-11-07-prosopo-gw-atelier-design.md` → `atelier/doc/design_v1.md` (§ 12)
- Delete : `app/` (`git rm -r app`), `run_app.sh`
- Modify : `pyproject.toml` racine (description, `members = ["core", "atelier"]`,
  `[tool.uv.sources] geneweb-py = { workspace = true }` inchangé), `uv.lock`
- Modify : `.github/workflows/ci.yml` (retirer le job `docker-build` ; ajouter lint/mypy/tests de
  l'atelier sur 3.11–3.13), `.gitignore` (retirer les exceptions `app/**`, ajouter
  `!atelier/tests/fixtures/*.gw` et `.superpowers/`)
- Modify : `AGENTS.md`, `CLAUDE.md`, `README.md`, `README.en.md`, `docs/img/pipeline.svg` si besoin
  (« application LLM (app/) » → atelier local)

**Interfaces :**
- Produces : `atelier/pyproject.toml` : `name = "prosopo-gw-atelier"`, `version = "0.1.0"`,
  `requires-python = ">=3.11"`, dépendances `geneweb-py>=0.1.0`, `fastapi`, `uvicorn`,
  `python-multipart`, `platformdirs` ; extra `dev` (pytest, pytest-cov, httpx, ruff, mypy) ;
  `[project.scripts] prosopo-gw-atelier = "prosopo_gw_atelier.cli:main"` ; mypy `strict = true`.

- [ ] **Step 1 :** `AGENTS.md`, les README, `core/AGENTS.md`, `core/doc/*` et `docs/img/pipeline.svg`
  portent des modifications locales non commitées (docs du 6 novembre) : **demander à
  l'utilisateur** s'il faut les commiter avant, pour ne pas mélanger les deux séries.
- [ ] **Step 2 :** `test_smoke.py` : `import prosopo_gw_atelier; import geneweb_py` ;
  `assert prosopo_gw_atelier.__version__ == "0.1.0"`.
- [ ] **Step 3 :** créer le membre, `uv lock`, `uv sync --all-packages --all-extras`, test vert.
- [ ] **Step 4 :** retrait d'`app/` et de `run_app.sh` ; `rg -n "app/docker|geneweb-app|run_app" --glob '!uv.lock'`
  ne renvoie plus que l'historique des docs de réflexion.
- [ ] **Step 5 :** `uv lock --check`, tests `core` et atelier verts.
- [ ] **Step 6 :** commits séparés : `build(atelier): add workspace member skeleton`,
  `chore(repo): remove the Streamlit app`, `ci: lint and test the atelier`.

## Lot B : données de référence (COG + codes postaux)

### Task 4 : construire et charger les données embarquées

**Files :**
- Create : `atelier/tools/build_refdata.py` (hors paquet, lancé à la main)
- Create : `atelier/src/prosopo_gw_atelier/refdata/__init__.py`, `refdata/loader.py`,
  `refdata/normalize.py`
- Create : `atelier/src/prosopo_gw_atelier/refdata/data/` (fichiers générés, commités)
- Create : `atelier/tests/fixtures/refdata_mini/` (extrait réduit, même format)
- Test : `atelier/tests/refdata/test_loader.py`, `test_normalize.py`

**Interfaces :**
- Produces :
  - `normalize(text: str) -> str` : minuscules, sans accents, `-`/`'`/`_`/espaces multiples → une
    espace, `st`→`saint`, `ste`→`sainte` (mots entiers), sans espaces de bord.
  - `@dataclass(frozen=True) Commune(insee: str, name: str, department: str, region: str)`
  - `@dataclass(frozen=True) NameMatch(commune: Commune, former_name: str | None)` :
    `former_name` rempli quand on a reconnu un ancien nom ou une commune fusionnée.
  - `class RefData` : `cog_vintage: str`, `postal_vintage: str`,
    `commune_by_insee(code: str) -> Commune | None`,
    `communes_by_name(name: str) -> list[NameMatch]` (nom normalisé, actuel ou ancien),
    `communes_by_postal(code: str) -> list[Commune]`,
    `department(token: str) -> str | None` (code ; accepte nom, numéro, `(59)`),
    `region(token: str) -> tuple[str, bool] | None` (nom canonique, `True` si région d'avant 2016),
    `country(token: str) -> str | None`.
  - `load_refdata(directory: Path | None = None) -> RefData` (défaut : `refdata/data`), mis en cache.

**Format des fichiers générés (choix du plan)** : CSV `;` UTF-8 compressés gzip, un par table :
`communes.csv.gz` (insee, nom, departement, region), `historique.csv.gz` (ancien_nom, insee_actuel,
date_effet), `departements.csv.gz`, `regions.csv.gz` (nom, avant_2016), `pays.csv.gz`,
`codes_postaux.csv.gz` (code_postal, insee), `VERSION` (`cog=<millésime>`, `postal=<millésime>`).

- [ ] **Step 1 :** `build_refdata.py` prend en arguments les chemins des fichiers **déjà
  téléchargés** (COG : communes, mouvements des communes, départements, régions actuelles et
  régions 2015, pays ; La Poste : base officielle des codes postaux) et les millésimes ; aucune
  requête réseau dans le script. Le `atelier/README.md` liste les pages sources sur insee.fr et
  data.gouv.fr (jeu `545b55e1c751df52de9b6045`, licence `lov2`, vérifiée le 7 novembre 2026).
  **Fichiers sources, déposés hors Git par l'utilisateur** (`_local_testdata/` est ignoré) :
  - `_local_testdata/refdata/cog-2026/` : `v_commune_2026.csv`, `v_commune_depuis_1943.csv`,
    `v_mvt_commune_2026.csv`, `v_departement_2026.csv`, `v_region_2026.csv`,
    `v_pays_territoire_2026.csv` (COG millésime 2026, insee.fr/fr/statistiques/fichier/8740222/) ;
  - `_local_testdata/refdata/cog-2015/` : le fichier des régions du millésime 2015 (régions
    d'avant 2016 ; page insee.fr/fr/information/2560452) ;
  - `_local_testdata/refdata/laposte/` : le CSV de la base officielle des codes postaux
    (`https://data.laposte.fr/data-fair/api/v1/datasets/laposte-hexasmal/raw`), millésime =
    date de téléchargement.
  Le script lit les en-têtes réels de ces fichiers (séparateur et encodage à détecter, ne pas
  supposer) et échoue avec un message clair si une colonne attendue manque.
- [ ] **Step 2 :** tests de `normalize` :
  `normalize("ST-OMER") == "saint omer"`, `normalize("Ste  Foy-lès-Lyon") == "sainte foy les lyon"`,
  `normalize("L'Haÿ-les-Roses") == "l hay les roses"`.
- [ ] **Step 3 :** tests du chargeur sur `refdata_mini` (extrait réel des fichiers générés,
  limité au Nord, au Pas-de-Calais, au Rhône, et à un nom porté par exactement deux communes
  de départements différents, choisi dans le COG) :
  `commune_by_insee("59512").name == "Roubaix"` ;
  `[c.insee for c in communes_by_postal("59100")] == ["59512"]` ;
  `department("Nord") == department("(59)") == department("59") == "59"` ;
  `region("Nord-Pas-de-Calais") == ("Nord-Pas-de-Calais", True)` ;
  `region("Hauts-de-France") == ("Hauts-de-France", False)` ;
  `country("FRANCE") == "France"` ;
  une commune fusionnée renvoie un `NameMatch` avec `former_name` rempli.
- [ ] **Step 4 :** implémenter, générer les vrais fichiers, vérifier leur taille (objectif :
  moins de 5 Mo au total) et que `git check-ignore` ne les ignore pas.
- [ ] **Step 5 :** test `load_refdata()` sur les vraies données : `cog_vintage` non vide,
  plus de 34 000 communes.
- [ ] **Step 6 :** commit `feat(atelier): embed INSEE COG and postal code reference data`.

## Lot C : moteur des lieux

### Task 5 : collecte et décomposition

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/places/model.py`, `places/collect.py`,
  `places/decompose.py`
- Create : `atelier/tests/fixtures/lieux_varies.gw` (personnes fictives ; lieux couvrant § 14 :
  casse, ville seule, ville + pays, ville + département + pays, région ancienne, code postal,
  code INSEE, avec et sans complément, ancien nom, abréviation `St`, homonymes dans deux
  départements, un lieu « en mer »)
- Test : `atelier/tests/places/test_collect.py`, `test_decompose.py`

**Interfaces :**
- Consumes : `RefData`, `normalize` (tâche 4) ; `build_base_tables`, `parse_place` (`core`).
- Produces (`places/model.py`) :
  - `ElementKind = Literal["commune", "postal_code", "insee_code", "department", "region", "country", "former_name"]`
  - `@dataclass(frozen=True) Element(kind: ElementKind, value: str, hint: str)` ; `hint` en
    français, affiché tel quel : `"nom"`, `"code postal"`, `"code INSEE"`, `"département"`,
    `"ancienne région"`, `"région"`, `"pays"`, `"ancien nom"`.
  - `@dataclass(frozen=True) Occurrence(table: str, row_id: str, column: str, complement: str | None, event_type: str | None, date: str | None)`
  - `@dataclass Writing(text: str, occurrences: list[Occurrence])` : `text` = `parse_place(raw).name`.
  - `@dataclass(frozen=True) Decomposition(writing: str, elements: tuple[Element, ...], insee: str | None, candidates: tuple[str, ...], ambiguous: bool)` :
    `insee` = commune résolue sans ambiguïté ; `candidates` = codes INSEE possibles sinon.
- Produces : `collect_writings(tables: Sequence[Table]) -> dict[str, Writing]` sur
  `personnes.naissance_lieu`, `personnes.deces_lieu`, `familles.mariage_lieu`, `evenements.lieu` ;
  une occurrence par cellule non vide (une naissance présente dans `personnes` et dans
  `evenements` compte deux fois : choix du plan, simple et cohérent avec les colonnes du pivot).
- Produces : `decompose(writing: str, ref: RefData) -> Decomposition`.

**Règles de `decompose` (fixées par § 6.1)** : segments coupés sur `,`, `(`, `)`, ` - ` et devant
un nombre à 5 caractères ; ordre libre. Un code à 5 caractères : code INSEE s'il existe dans le
COG, code postal s'il existe dans la base La Poste ; s'il est les deux, on retient celui qui
s'accorde avec la commune écrite ; s'il n'est ni l'un ni l'autre, `ambiguous=True` et aucun
élément code. Un code postal seul donne `candidates` = ses communes, sans `insee`.

- [ ] **Step 1 :** test `collect_writings` sur la fixture : `"Lyon"` et
  `"[Atelier Rose]_-_Lyon"` donnent la même clé `"Lyon"`, avec deux occurrences dont une porte
  `complement == "Atelier Rose"`.
- [ ] **Step 2 :** tests paramétrés de `decompose` (attendu : `insee`, éléments par `kind`) :
  `"ROUBAIX, Nord, France"` → `59512`, department `59`, country `France` ;
  `"59100 Roubaix"` → `59512`, élément `postal_code` ; `"59512"` → `59512`, hint `"code INSEE"` ;
  `"roubaix, Nord-Pas-de-Calais"` → hint `"ancienne région"` ; `"St-Omer (62)"` → commune Saint-Omer ;
  un nom d'homonyme seul → `insee is None`, `len(candidates) == 2` ;
  `"99999"` → `ambiguous is True` ; `"59100"` seul → `candidates == ("59512",)`, `insee is None`.
- [ ] **Step 3 :** implémenter ; tests verts.
- [ ] **Step 4 :** commit `feat(atelier): collect and decompose place writings`.

### Task 6 : regroupement en clusters

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/places/cluster.py`
- Test : `atelier/tests/places/test_cluster.py`

**Interfaces :**
- Consumes : `Decomposition`, `RefData`, `normalize`.
- Produces :
  - `Confidence = Literal["high", "medium", "low"]`
  - `@dataclass Cluster(id: str, writings: list[str], proposal: dict[ElementKind, str], confidence: Confidence, anchor_place_id: str | None = None)`
    — `id` déterministe : `"insee:<code>"` ou `"name:<clé normalisée>"` ; `anchor_place_id` = lieu
    déjà validé auquel ces écritures ressemblent.
  - `build_clusters(decompositions: Mapping[str, Decomposition], ref: RefData, known: Mapping[str, KnownPlace]) -> list[Cluster]`
    où `KnownPlace(place_id: str, insee: str | None, name_key: str)` décrit un lieu déjà validé.

**Règles (§ 6.2)** : `insee` résolu → clé forte, `high` si tiré d'un code ou de nom +
département, `medium` si nom unique dans le COG ; sinon clé « nom normalisé + département » →
`low`. Un nom sans département présent dans plusieurs départements n'est jamais fusionné
(`low`, cluster à part). Similarité `difflib` seulement à l'intérieur de blocs (même première
lettre normalisée et même département ou département inconnu) ; une fusion par similarité est
au mieux `medium`. Seuil : au constructeur (§ 13). `proposal` : éléments majoritaires du cluster,
complétés par le COG quand `insee` est connu. Tri : confiance, puis occurrences décroissantes
(fait par l'appelant, qui a les occurrences).

- [ ] **Step 1 :** tests : les 5 écritures de Roubaix de la fixture forment un cluster
  `insee:59512`, `high` ; les deux homonymes restent deux clusters `low` ; une écriture nouvelle
  `"Roubaix (Nord)"` avec `known` contenant 59512 a `anchor_place_id` rempli ;
  `"Lile"` et `"Lille"` fusionnent au mieux en `medium`.
- [ ] **Step 2 (Review Focus 4) :** `test_clusters_large_input` : 20 000 écritures synthétiques
  (communes du COG + suffixes aléatoires fixés par graine) → `build_clusters` en moins de 10 s.
- [ ] **Step 3 :** implémenter ; tests verts.
- [ ] **Step 4 :** commit `feat(atelier): cluster place writings`.

### Task 7 : référentiel personnel (décisions et journal)

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/store/registry.py`, `store/schema.sql`, `store/paths.py`
- Test : `atelier/tests/store/test_registry.py`

**Interfaces :**
- Produces (`store/paths.py`) : `data_dir() -> Path` : `$PROSOPO_GW_ATELIER_HOME` sinon
  `platformdirs.user_data_dir("prosopo-gw-atelier")` ; `registry_path() -> Path` = `data_dir() / "referentiel.sqlite"`.
- Produces (`store/registry.py`) :
  - `Origin = Literal["rule", "manual", "reference", "llm"]`
  - `@dataclass(frozen=True) Place(place_id: str, fields: dict[ElementKind, str], origins: dict[ElementKind, Origin])`
  - `@dataclass(frozen=True) Decision(writing: str, place_id: str | None, status: Literal["validated", "rejected"], project: str | None)`
  - `@dataclass(frozen=True) JournalEntry(entry_id: int, at: str, project: str | None, action: str, payload: dict[str, Any], undone: bool)`
  - `class PlaceRegistry(path: Path)` :
    `decision(writing: str) -> Decision | None` ; `decisions(writings: Iterable[str]) -> dict[str, Decision]` ;
    `place(place_id: str) -> Place` ; `known_places() -> list[KnownPlace]` ;
    `validate(writings: Sequence[str], fields: Mapping[ElementKind, str], origins: Mapping[ElementKind, Origin], project: str, place_id: str | None = None) -> str` ;
    `reject(writings: Sequence[str], project: str) -> None` ;
    `correct(place_id: str, field: ElementKind, value: str, project: str) -> None` ;
    `detach(writings: Sequence[str], project: str) -> None` ;
    `undo(entry_id: int) -> None` ; `journal(limit: int | None = None) -> list[JournalEntry]`.

**Règles** : `validate` associe **en une seule transaction** toutes les écritures au même
`place_id` (UUID4 si nouveau), une ligne par écriture exacte (§ 6.3, précision de l'auteur) ;
une écriture déjà décidée ailleurs est réassociée et l'ancienne valeur va dans le journal.
Actions journalisées : `validate`, `reject`, `correct`, `detach`, `undo`, `import`. Chaque
entrée garde l'état avant et après des lignes touchées, ce qui rend `undo` exact. Le journal
n'est jamais effacé ; `undo` ajoute une entrée et marque l'originale `undone`. Connexion :
`PRAGMA journal_mode=WAL`, `busy_timeout=5000`, `user_version` pour le schéma.

- [ ] **Step 1 :** tests : `validate(["Roubaix", "ROUBAIX"], …)` → les deux écritures ont le même
  `place_id` et une seule entrée de journal `validate` ; `undo` de cette entrée → `decision("Roubaix") is None` ;
  `reject(["en mer"])` → statut `rejected` ; `correct` change le champ et l'origine passe à `manual`.
- [ ] **Step 2 (Review Focus 3) :** le fichier n'existe pas → créé ; deux `PlaceRegistry` sur le
  même chemin, écritures alternées → aucune `sqlite3.OperationalError`.
- [ ] **Step 3 :** implémenter ; tests verts.
- [ ] **Step 4 :** commit `feat(atelier): personal place registry with replayable journal`.

### Task 8 : projet et rechargement

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/project.py`
- Test : `atelier/tests/test_project.py`

**Interfaces :**
- Consumes : tâches 5 à 7, `GeneWebParser`, `build_base_tables`.
- Produces :
  - `ClusterState = Literal["todo", "validated", "rejected", "already_decided"]`
  - `@dataclass ClusterView(cluster: Cluster, state: ClusterState, occurrences: int, parent_id: str | None, provisional_name: str | None)`
  - `class Project` :
    `open(gw_path: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path) -> Project` (classmethod) ;
    `project_id: str` (empreinte du chemin absolu) ; `gw_changed: bool` (sha256 du contenu différent de la dernière ouverture) ;
    `tables: list[Table]` ; `writings: dict[str, Writing]` ;
    `clusters() -> list[ClusterView]` (triés : parent puis enfants, confiance, occurrences) ;
    `cluster(cluster_id: str) -> ClusterView` ;
    `split(cluster_id: str, writings: Sequence[str]) -> ClusterView` (le nouveau, `parent_id` = origine, `provisional_name` = première écriture) ;
    `reload() -> None` (reparse le `.gw`, garde décisions et scissions).
  - État du projet : `projects_dir / f"{project_id}.sqlite"` (chemin, empreinte, scissions), à part du référentiel.

**Règles (§ 6.3, § 6.4)** : une écriture déjà décidée est rattachée d'office ; un cluster dont
toutes les écritures sont décidées est `validated` si la décision vient de ce projet,
`already_decided` sinon ; une écriture nouvelle proche d'un lieu validé rejoint son cluster
(`anchor_place_id`), qui redevient `todo`. Une écriture du référentiel absente du `.gw` est ignorée.

- [ ] **Step 1 :** test « aucune décision à refaire » : ouvrir la fixture, valider tous les
  clusters, rouvrir → tous `validated` ; ouvrir une copie modifiée (une écriture ajoutée
  `"Roubaix (59)"`) → un seul cluster `todo`, ancré sur Roubaix ; ouvrir une **autre** fixture
  `autre_base.gw` partageant `"Lyon"` → `"Lyon"` est `already_decided`.
- [ ] **Step 2 :** test `split` : le nouveau cluster suit son parent dans `clusters()`,
  `provisional_name` égal à la première écriture sortie ; la scission survit à `reload()`.
- [ ] **Step 3 :** test `gw_changed` : vrai après modification du fichier, faux sinon.
- [ ] **Step 4 :** implémenter ; tests verts.
- [ ] **Step 5 :** commit `feat(atelier): projects that reapply past decisions on reload`.

### Task 9 : export et import du référentiel

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/store/exchange.py`
- Test : `atelier/tests/store/test_exchange.py`

**Interfaces :**
- Produces :
  - `export_registry(registry: PlaceRegistry) -> dict[str, Any]` :
    `{"format": "prosopo-gw-atelier/lieux", "version": 1, "exported_at": …, "places": [...], "writings": [...]}`
  - `@dataclass(frozen=True) Conflict(writing: str, current: Decision, incoming: Decision)`
  - `import_registry(registry: PlaceRegistry, data: Mapping[str, Any]) -> list[Conflict]` :
    applique tout ce qui n'entre pas en conflit (une entrée de journal `import`), renvoie les conflits.
  - `resolve_conflict(registry: PlaceRegistry, conflict: Conflict, keep: Literal["current", "incoming"], project: str | None) -> None`
  - `class RegistryFormatError(ValueError)`

- [ ] **Step 1 :** tests : aller-retour export → import dans un référentiel vide → mêmes
  décisions ; une écriture décidée différemment → un `Conflict`, valeur actuelle inchangée ;
  `resolve_conflict(..., "incoming")` l'applique.
- [ ] **Step 2 (Review Focus 5) :** `format` autre ou `version` 2 → `RegistryFormatError`,
  aucune ligne écrite (compter les décisions avant et après).
- [ ] **Step 3 :** implémenter ; tests verts.
- [ ] **Step 4 :** commit `feat(atelier): export and import the personal place registry`.

## Lot D : sortie pivot

### Task 10 : tables pivot et archive

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/export/pivot.py`, `export/archive.py`,
  `export/LISEZMOI.txt` (gabarit)
- Test : `atelier/tests/export/test_pivot.py`, `test_archive.py`

**Interfaces :**
- Consumes : `Project.tables`, `PlaceRegistry`, `RefData`, writers de `core`.
- Produces :
  - `LIEUX: TableSpec` : `lieu_id` (clé), `commune`, `code_insee`, `code_postal`, `departement`,
    `region`, `pays`, `ancien_nom`, puis `<champ>_origine` pour chacun (§ 9).
  - `ECRITURES_LIEUX: TableSpec` : `ecriture`, `lieu_id`, `statut`.
  - `build_pivot(tables: Sequence[Table], registry: PlaceRegistry) -> list[Table]` :
    tables de `core` dans leur ordre, avec, insérées juste après la colonne de lieu :
    `personnes` : `naissance_lieu_id`, `naissance_complement`, `deces_lieu_id`, `deces_complement` ;
    `familles` : `mariage_lieu_id`, `mariage_complement` ; `evenements` : `lieu_id` (`complement`
    existe déjà). Puis `lieux` (lieux référencés par ce `.gw` seulement) et `ecritures_lieux`.
  - `build_archive(project: Project, registry: PlaceRegistry, ref: RefData, generated_at: datetime) -> bytes` :
    zip contenant `LISEZMOI.txt`, `dictionnaire.csv`, un CSV par table, `<base>.json`,
    `<base>.sqlite` ; **pas** de `base.org.json` (§ 9).

- [ ] **Step 1 :** tests : les colonnes d'origine de `core` sont inchangées et dans le même ordre
  (comparer `spec.column_names` en retirant les colonnes ajoutées) ; une écriture validée a son
  `…_lieu_id` ; une non validée a `None` et garde son écriture d'origine ;
  `[Atelier Rose]_-_Lyon` → `lieu_id` de Lyon et `complement == "Atelier Rose"`.
- [ ] **Step 2 :** test d'archive : liste exacte des fichiers ; `LISEZMOI.txt` contient les deux
  millésimes et la mention « Licence Ouverte 2.0 » ; aucun `*.org.json`.
- [ ] **Step 3 :** implémenter avec `table_to_csv`, `tables_to_json`, `tables_to_sqlite`,
  `dictionary_table` de `core` ; tests verts.
- [ ] **Step 4 :** commit `feat(atelier): export the pivot with a places table`.

## Lot E : webapp locale

### Task 11 : serveur, API et commande

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/web/app.py`, `web/schemas.py`, `cli.py`
- Test : `atelier/tests/web/test_api.py`, `atelier/tests/test_cli.py`

**Interfaces :**
- Consumes : tâches 4 à 10.
- Produces : `create_app(project: Project, registry: PlaceRegistry, ref: RefData) -> FastAPI` ;
  `main(argv: Sequence[str] | None = None) -> int` : `prosopo-gw-atelier BASE.gw [--port N] [--no-browser] [--data-dir DIR]`.
- Produces : routes (JSON, clés anglaises). **Aucune écriture dans un chemin d'URL** :
  - `GET /api/project` → `{gw_name, gw_changed, counts: {total, todo, validated, rejected, already_decided}, cog_vintage, postal_vintage}`
  - `POST /api/project/reload`
  - `GET /api/clusters?state=` → liste de `ClusterView` résumés (`id`, `label`, `state`, `confidence`, `occurrences`, `parent_id`)
  - `GET /api/clusters/{cluster_id}` → `proposal`, `complements` (distincts, avec occurrences), `writings` (`text`, `occurrences`, `hint`, `decided`)
  - `POST /api/clusters/{cluster_id}/validate` `{fields, checked}` → sort d'abord les non cochées, puis valide ; renvoie `{place_id, split: ClusterSummary | null}`
  - `POST /api/clusters/{cluster_id}/split` `{writings}` → `ClusterSummary` du nouveau
  - `POST /api/clusters/{cluster_id}/reject`
  - `PATCH /api/places/{place_id}` `{field, value}`
  - `POST /api/occurrences` `{writing}` → occurrences (personne/famille, type, date)
  - `POST /api/undo` → dernière action de la session (pile en mémoire de références
    `("registry", entry_id)` ou `("project", split_id)`)
  - `GET /api/export` → zip ; `GET /api/registry/export` ; `POST /api/registry/import` → conflits ;
    `POST /api/registry/conflicts/resolve` `{writing, keep}`
  - `GET /` et `/static/…` : interface (tâche 12)
- `TrustedHostMiddleware` (`127.0.0.1`, `localhost`) ; uvicorn sur `127.0.0.1`, port libre si
  `--port` absent ; ouverture du navigateur sauf `--no-browser`.

- [ ] **Step 1 :** tests `TestClient` du parcours : `GET /api/clusters` → validate du cluster
  Roubaix avec une écriture décochée → `split` non nul et décision enregistrée pour les cochées ;
  `undo` → décision annulée ; `GET /api/export` → zip valide.
- [ ] **Step 2 (Review Focus 2) :** écriture `"Paris / Seine ? #1 \"bis\""` dans une fixture :
  `POST /api/occurrences` la retrouve, et elle revient intacte dans le détail du cluster.
- [ ] **Step 3 (Review Focus 1) :** fixture `sans_lieux.gw` : `counts.total == 0`,
  `GET /api/clusters == []`, export valide avec `lieux` vide.
- [ ] **Step 4 :** test d'hôte : en-tête `Host: evil.example` → 400.
- [ ] **Step 5 :** test CLI : `main(["absent.gw", "--no-browser"])` → code 2 et message
  « Fichier introuvable » ; le serveur n'est pas lancé dans les tests (lanceur injectable).
- [ ] **Step 6 :** implémenter ; tests verts.
- [ ] **Step 7 :** commit `feat(atelier): local API and command line launcher`.

### Task 12 : écran liste + détail

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/web/static/index.html`, `app.js`, `style.css`,
  `vendor/` (copie de `core/src/geneweb_py/api/static/vendor/` : Bootstrap, Tabulator)
- Modify : `atelier/pyproject.toml` (inclure `static/**` dans le paquet)
- Test : `atelier/tests/web/test_static.py` ; vérification manuelle dans le navigateur

**Comportement (§ 7, validé par prototype)** : file à gauche (états, filtres, compteur
« N clusters · M traités », enfants sous leur parent avec ↳, clignotement du nouveau lieu) ;
détail à droite (forme retenue en champs modifiables, compléments à part, écritures avec case,
occurrences, indice ; écritures décochées barrées et estompées) ; boutons Valider, « Sortir les
décochées vers un nouveau lieu (n) » (grisé à 0), Rejeter, Voir les occurrences, Annuler ;
bandeau après une sortie avec « Ouvrir le nouveau lieu », on reste sur le lieu d'origine ;
raccourcis V, S, R, O, ↑/↓, Ctrl+Z ; avertissement si `gw_changed`. Référence visuelle :
`.superpowers/brainstorm/153878-1794081947/content/prototype-lieux-v2.html` (non versionné, ne pas
recopier son code).

- [ ] **Step 1 :** `test_static.py` : `GET /` → 200, contient `app.js` ; le paquet construit
  (`uv build --package prosopo-gw-atelier`) contient `static/vendor/tabulator.min.js`.
- [ ] **Step 2 :** implémenter.
- [ ] **Step 3 :** vérification au navigateur sur `lieux_varies.gw` : valider Roubaix avec une
  écriture décochée → bandeau, nouveau lieu sous Roubaix, Ctrl+Z le défait ; aucune erreur
  console.
- [ ] **Step 4 :** commit `feat(atelier): cluster validation screen`.

### Task 13 : référentiel dans l'interface et export

**Files :**
- Modify : `web/static/index.html`, `app.js`
- Test : vérification manuelle ; tests API déjà en tâche 11

**Comportement :** bouton « Exporter les données » (zip pivot) ; menu « Référentiel » :
exporter, importer, puis liste des conflits à trancher un par un (« garder l'actuel » /
« prendre l'importé ») ; journal des dernières actions en lecture.

- [ ] **Step 1 :** implémenter.
- [ ] **Step 2 :** vérification : export du référentiel, import dans un autre dossier
  (`--data-dir`), conflit fabriqué à la main, tranché à l'écran.
- [ ] **Step 3 :** commit `feat(atelier): registry exchange and export in the UI`.

## Lot F : publication

### Task 14 : publier `core` puis l'atelier

**Files :**
- Create : `.github/workflows/release.yml`
- Modify : `core/pyproject.toml`, `atelier/pyproject.toml` (métadonnées : `readme`, `urls`,
  `license`), `atelier/README.md` (installation `uv tool install prosopo-gw-atelier`)

- [ ] **Step 1 :** vérifier la disponibilité des noms sur PyPI (`geneweb-py`, et le nom
  définitif de l'atelier) ; **le nom définitif doit être choisi avant cette tâche**.
- [ ] **Step 2 :** workflow déclenché par les étiquettes `core-v*` et `atelier-v*` :
  `uv build --package <paquet>` puis `pypa/gh-action-pypi-publish` en publication de confiance
  (aucune clé dans le dépôt).
- [ ] **Step 3 :** vérification locale : `uv build --package geneweb-py` et
  `uv build --package prosopo-gw-atelier` ; installer la roue de l'atelier dans un
  environnement vide avec celle de `core` : `prosopo-gw-atelier --help` répond.
- [ ] **Step 4 :** commit `ci: publish packages to PyPI on version tags`. La configuration de
  PyPI et la pose des étiquettes restent à l'utilisateur.

---

## Ordre et dépendances

```
A1 ─ A2 ─ A3 ─ B4 ─ C5 ─┬─ C6 ──────┬─ C8 ─ D10 ─ E11 ─ E12 ─ E13 ─ F14
                        └─ C7 ─ C9 ─┘
```

A1 et A2 sont indépendants du reste. Après C5 (qui fixe `ElementKind`), C6 et C7–C9 peuvent
avancer en parallèle. F14 attend le nom définitif.
