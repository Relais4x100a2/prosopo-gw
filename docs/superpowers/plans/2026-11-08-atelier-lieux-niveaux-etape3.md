# Atelier : sources externes et DicoTopo (étape 3), plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** poser l'architecture des sources externes (configuration locale, cache commun, file de fond qui reprend après redémarrage, interface de source) et brancher DicoTopo : téléchargement à la demande par département, index local, propositions de `lieu_dit` et de noms anciens, écran Sources.

**Architecture :** un paquet `sources/` porte l'interface commune (`Source`, `LevelQuery`, `SourceCandidate`), la file de tâches (SQLite dans le cache, un fil d'exécution dans le processus de l'atelier) et le stockage des résultats. Les résultats ne touchent jamais le référentiel : le projet les superpose aux chaînes comme niveaux **proposés** ; accepter passe par les gestes existants (journalisés), refuser est mémorisé dans le référentiel (schéma 4). DicoTopo est la première source : `DTxx.xml` téléchargé dans le cache, indexé en SQLite, codes INSEE 2011 ramenés à la commune actuelle par le COG.

**Tech Stack :** Python ≥ 3.11, workspace `uv`, SQLite, `xml.etree.ElementTree.iterparse`, `urllib.request`, `threading`, FastAPI + Pydantic, JavaScript sans framework, pytest, ruff, mypy strict. Aucune nouvelle dépendance.

**Spec :** `docs/superpowers/specs/2026-11-08-atelier-lieux-niveaux-design.md` (§ 3 contraintes et licences, 7, 9 « Écran Sources », 10, 11 `LISEZMOI`, 13 étape 3, 14, 15 « DicoTopo »). Prérequis : étapes 1 et 2 dans `main` (niveaux, référentiel schéma 3 et sa montée générique).

## Global Constraints

- Dépôt **public** : fixtures synthétiques uniquement ; jamais de `*.gw`/`*.ged` réel ; ne jamais lire `_local_testdata/bases/`.
- **Rien de DicoTopo (CC BY-NC-ND 3.0 FR) dans le dépôt, les fixtures publiées ou le paquet.** Les tests utilisent un extrait **synthétique** au même format XML (noms de communes réels permis, formes anciennes et définitions inventées). Un vrai `DTxx.xml` ne s'ouvre que dans le cache local ou le scratchpad, jamais sous le dépôt.
- **Aucune requête réseau dans les tests** : un `conftest.py` autouse remplace `urllib.request.urlopen` par une fonction qui lève une erreur ; les tests de téléchargement passent un `opener` factice.
- Chaque source en ligne **s'active explicitement** ; seuls des noms de lieux, des codes et des identifiants partent sur le réseau (jamais un nom de personne, une date ou un complément).
- Les résultats d'une source arrivent comme **propositions**, jamais comme décisions. DicoTopo **ne fixe jamais la commune actuelle** : elle vient toujours du COG.
- Export : un niveau d'origine `dicotopo` porte l'identifiant `P…`, le lien vers l'article et la mention de la source ; le nom exporté est celui que l'utilisateur a validé ; formes anciennes et commentaires **non exportés**.
- `git add` avec chemins explicites, puis `git diff --cached --name-only` ; ni `git push`, ni `--force`, ni étiquette sans accord explicite. Branche `feat/atelier-sources-dicotopo`.
- `uv` exclusivement ; mêmes commandes de tests, lint et types que l'étape 2. Code et commits en anglais (avec `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`), textes affichés et documentation en français. `core` non modifié.

## Choix de ce plan (à relire)

1. **Emplacements.** Configuration locale : `data_dir()/config.json` (sources activées, plus tard l'identifiant GeoNames), droits `0600` à l'écriture. Cache commun : `data_dir()/cache/` ; `cache/sources.sqlite` (file et résultats), `cache/dicotopo/DTxx.xml`, `cache/dicotopo/index.sqlite`.
2. **Les résultats ne sont pas écrits dans le référentiel.** Ils vivent dans le cache (table `results`, clé `(source, query_key)`) et le projet les superpose comme niveaux `status="proposed"`. Ainsi la file de fond n'écrit jamais dans le référentiel, et `Annuler` ne défait jamais un travail de fond. Vider le cache fait disparaître les propositions non encore acceptées (elles reviendront au prochain passage de la file).
3. **Refus mémorisé** dans le référentiel, table `refused_proposals(subject, source, identifier, project, decided_at)` (schéma 4, montée générique de l'étape 2) ; `subject` vaut `writing:<écriture>` pour un cluster non validé et `place:<place_id>` pour un lieu validé. Journal : action `correct`, charge `{"kind": "refuse_source_proposal", …}`. Export JSON du référentiel : liste facultative `propositions_refusees`.
4. **Accepter une proposition** : sur un cluster non validé, l'écran l'ajoute à la chaîne en cours d'édition (comportement actuel des propositions de règle, `app.js`). Sur un lieu validé, nouvelle route qui insère le niveau comme validé (`set_levels`, journal `correct`).
5. **File de fond** : un seul fil d'exécution démon, démarré par `create_app` (paramètre `start_worker: bool = True`, faux dans les tests de l'API). Les tâches `running` au démarrage repassent `pending` (reprise). Trois essais, attente 30 s, 5 min, 1 h ; ensuite `failed` avec le message, relançable depuis l'écran. Priorité entière : nombre d'occurrences du cluster ; un cluster ouvert à l'écran passe à `1_000_000_000`.
6. **Limites de débit** : intervalle minimal entre deux requêtes d'une même source (DicoTopo API : 1 s ; GitHub brut : 1 s). La file n'exécute qu'une tâche à la fois.
7. **Ce que DicoTopo propose**, pour un cluster français dont le département est connu (écrit ou déduit) et couvert localement :
   - **niveau écrit non reconnu** sous une commune résolue (`Marconne, Hesdin-la-Forêt`) : article dont une forme (vedette ou forme ancienne) a la même clé et dont la commune, ramenée à l'actuelle, est celle du cluster → niveau proposé `lieu_dit` ;
   - **écriture sans commune résolue** (`Marcona`) : article du département dont une forme a la même clé → chaîne proposée `lieu_dit` (DicoTopo) + `commune_historique` éventuelle et `commune` (origine `insee`, depuis le COG) ; si l'article **est** une commune (pas de `localisation`, code INSEE propre), la proposition est la commune avec `written` = forme écrite (nom ancien reconnu) ;
   - plusieurs articles ou communes différentes pour la même clé → aucune proposition unique ; le cluster porte les lectures en **alternatives** (mécanisme de l'étape 1) ;
   - commune de l'article ≠ commune résolue du cluster → rien (la commune ne change pas).
8. **API DicoTopo** (dernier recours) : activée par l'utilisateur dans l'écran Sources (désactivée par défaut). Seulement pour un département **non téléchargé** et non couvert localement ; jamais de parcours de la collection `/places`. Les points d'accès exacts (recherche par libellé et département, article par identifiant) sont vérifiés à la Task 6 et notés dans la docstring.
9. **Lien et source d'un niveau DicoTopo** : `identifier = "P93132264"`, `source = "DicoTopo, https://dicotopo.cths.fr/places/P93132264"` (motif du lien vérifié à la Task 6). L'export garde ces deux colonnes telles quelles.
10. **Couverture** : liste des `DTxx` lue une fois par l'API GitHub des contenus (`https://api.github.com/repos/chartes/dico-topo/contents/data`) et gardée dans `cache/dicotopo/coverage.json` ; sans réseau, la liste mise en cache (ou vide) est montrée.

## Review Focus

- **Atelier fermé pendant un téléchargement** : au redémarrage, le fichier partiel n'est jamais indexé, la tâche reprend du début. → Task 2 `test_running_jobs_resume_as_pending`, Task 5 `test_partial_download_is_never_indexed`.
- **Service en panne ou qui refuse** (erreur 500, 429, délai dépassé, réponse non XML) : la tâche est retentée puis marquée `failed` avec un message français ; aucune exception ne remonte à l'écran. → Task 2 `test_failure_backoff_then_failed`, Task 6 `test_api_error_is_recorded`.
- **XML DicoTopo inattendu** (article sans vedette, sans code INSEE, balises inconnues, entités) : article ignoré et compté, l'index se construit quand même. → Task 4 `test_malformed_articles_are_skipped`.
- **Lieux-dits homonymes dans un même département** : deux articles, deux communes → alternatives, jamais un choix silencieux. → Task 7 `test_homonyms_give_alternatives`.
- **Une proposition refusée revient** après rechargement, vidage du cache ou nouveau passage de la file : elle ne doit pas revenir. → Task 7 `test_refused_proposal_stays_refused`.

---

## Fichiers

| Fichier | Rôle | Tâches |
|---|---|---|
| `atelier/src/prosopo_gw_atelier/store/config.py` | configuration locale, `cache_dir()` | 1 |
| `atelier/tests/conftest.py` | interdiction du réseau dans les tests | 1 |
| `atelier/src/prosopo_gw_atelier/sources/base.py` | interface de source | 2 |
| `atelier/src/prosopo_gw_atelier/sources/queue.py` | file de fond, résultats, limites de débit | 2 |
| `atelier/src/prosopo_gw_atelier/sources/fetch.py` | téléchargement HTTP sûr (temporaire puis renommage) | 3 |
| `atelier/src/prosopo_gw_atelier/refdata/loader.py` | `RefData.current_of` (code INSEE ancien → commune actuelle) | 4 |
| `atelier/src/prosopo_gw_atelier/sources/dicotopo/index.py` | lecture XML, index SQLite | 4 |
| `atelier/tests/fixtures/dicotopo/DT62.xml`, `DT59.xml` | extraits synthétiques | 4 |
| `atelier/src/prosopo_gw_atelier/sources/dicotopo/download.py` | couverture, téléchargement, indexation | 5 |
| `atelier/src/prosopo_gw_atelier/sources/dicotopo/source.py` | `DicoTopoSource` (local, API) et règles de proposition | 6 |
| `atelier/src/prosopo_gw_atelier/store/registry.py`, `schema.sql`, `exchange.py` | `refused_proposals`, schéma 4 | 7 |
| `atelier/src/prosopo_gw_atelier/project.py` | file alimentée, propositions superposées | 7 |
| `atelier/src/prosopo_gw_atelier/web/app.py`, `schemas.py`, `cli.py` | API Sources, fil de fond, routes de propositions | 8 |
| `atelier/src/prosopo_gw_atelier/web/static/app.js`, `style.css`, `index.html` | écran Sources, propositions DicoTopo | 9 |
| `atelier/src/prosopo_gw_atelier/export/pivot.py`, `LISEZMOI.txt`, `archive.py` | niveaux `dicotopo`, attribution | 10 |
| `atelier/README.md`, `docs/reflexions/points-ouverts.md` | documentation | 10 |

---

### Task 1 : configuration locale et cache commun

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/store/config.py`, `atelier/tests/conftest.py`
- Test: `atelier/tests/store/test_config.py`

**Interfaces:**
- Produces:
  - `cache_dir() -> Path` (`data_dir() / "cache"`, créé à la demande).
  - `@dataclass class LocalConfig: dicotopo_api: bool = False; geonames_username: str | None = None; extra: dict[str, object]` (clés inconnues gardées telles quelles à la réécriture).
  - `load_config(path: Path | None = None) -> LocalConfig` (fichier absent ou JSON invalide → valeurs par défaut, sans exception) ; `save_config(config: LocalConfig, path: Path | None = None) -> None` (écriture atomique, droits `0600`).
  - `tests/conftest.py` : fixture autouse `no_network` (`monkeypatch.setattr(urllib.request, "urlopen", _refuse)`), et fixture autouse qui pointe `PROSOPO_GW_ATELIER_HOME` sur `tmp_path` pour qu'aucun test n'écrive dans le dossier de l'utilisateur.

- [ ] **Step 1 : tests qui échouent** : `test_default_config_when_missing`, `test_invalid_json_gives_defaults`, `test_round_trip_keeps_unknown_keys`, `test_config_file_is_private` (`stat.S_IMODE(mode) == 0o600`, sauté sous Windows), `test_network_is_forbidden_in_tests` (`urlopen` lève).
- [ ] **Step 2 : lancer** `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/store/test_config.py -v` → échec.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 : relancer toute la suite** → PASS (la fixture d'environnement ne casse aucun test existant).
- [ ] **Step 5 : commit** `feat(atelier): add the local config and the shared source cache`.

---

### Task 2 : interface de source et file de fond

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/__init__.py`, `sources/base.py`, `sources/queue.py`
- Test: `atelier/tests/sources/test_queue.py`

**Interfaces:**
- Consumes: `cache_dir()` (Task 1), `Level` (étape 1).
- Produces:
  - `base.py` :
    - `@dataclass(frozen=True) class LevelQuery: name: str; type: str | None; parents: tuple[str, ...]; country: str | None; department: str | None; insee: str | None` et `key() -> str` (JSON trié des champs normalisés, clé de cache stable).
    - `@dataclass(frozen=True) class SourceCandidate: source: str; identifier: str; name: str; type: str | None; parents: tuple[Level, ...]; start: str | None; end: str | None; latitude: float | None; longitude: float | None; link: str | None; insee: str | None`.
    - `class Source(Protocol): name: str; def search(self, query: LevelQuery) -> list[SourceCandidate]: ...; def article(self, identifier: str) -> SourceCandidate | None: ...; def covers(self, query: LevelQuery) -> bool: ...` (couverture **locale** ; l'API est un mode interne de la source).
    - `class SourceError(Exception)` (message en français, affichable).
  - `queue.py` :
    - `JobKind = Literal["download", "index", "match"]` ; `JobState = Literal["pending", "running", "done", "failed"]`.
    - `@dataclass(frozen=True) class Job: id: int; source: str; kind: JobKind; key: str; payload: dict[str, object]; priority: int; state: JobState; attempts: int; error: str | None; not_before: str | None`.
    - `class SourceQueue(path: Path, clock: Callable[[], float] = time.time)` : `enqueue(source, kind, key, payload, priority) -> int` (une tâche non terminée de même `(source, kind, key)` n'est pas dupliquée ; sa priorité monte au maximum des deux) ; `bump(source, key, priority)` ; `next_job() -> Job | None` (`pending`, `not_before` passé, priorité décroissante puis ancienneté) ; `finish(job_id)` ; `fail(job_id, message)` (choix 5) ; `retry_failed(source: str | None = None)` ; `resume()` (`running` → `pending`) ; `counts() -> dict[str, dict[JobState, int]]` ; `errors(limit: int = 20) -> list[Job]` ; `store_result(source, query_key, candidates: list[SourceCandidate])` ; `result(source, query_key) -> list[SourceCandidate] | None` (`None` = jamais cherché) ; `clear(source: str)` (tâches et résultats de la source).
    - `class RateLimiter(min_interval: float, clock, sleep)` : `wait()`.
    - `class Worker(queue: SourceQueue, handlers: Mapping[tuple[str, JobKind], Callable[[Job], None]])` : `run_once() -> bool` (exécute une tâche, `False` s'il n'y en a pas) ; `start()` / `stop()` (fil démon qui appelle `run_once`, attend 1 s quand la file est vide).

- [ ] **Step 1 : tests qui échouent** (sans fil d'exécution, horloge factice) : `test_priority_order`, `test_enqueue_is_idempotent_and_raises_priority`, `test_running_jobs_resume_as_pending`, `test_failure_backoff_then_failed` (30 s, 300 s, 3600 s puis `failed`, message gardé), `test_retry_failed`, `test_results_round_trip_and_unknown_is_none`, `test_clear_source`, `test_rate_limiter_waits` (sommeil factice), `test_worker_run_once_calls_handler`, `test_handler_exception_marks_failure` (une `SourceError` garde son message ; une autre exception donne « Erreur inattendue : <type> »).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS ; mypy.
- [ ] **Step 5 : commit** `feat(atelier): add the source interface and the background queue`.

---

### Task 3 : téléchargement HTTP

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/fetch.py`
- Test: `atelier/tests/sources/test_fetch.py`

**Interfaces:**
- Produces:
  - `Opener = Callable[[urllib.request.Request, float], BinaryIO]` (par défaut `urllib.request.urlopen` avec délai).
  - `USER_AGENT = "prosopo-gw-atelier/<version> (+https://github.com/<dépôt>)"` (le constructeur reprend l'URL du dépôt dans `atelier/pyproject.toml` ; aucun courriel).
  - `download(url: str, target: Path, *, opener: Opener | None = None, timeout: float = 60.0, max_bytes: int | None = None) -> int` : écrit dans `target.with_suffix(target.suffix + ".part")`, renomme à la fin, rend la taille ; toute erreur supprime le `.part` et lève `SourceError` (« Téléchargement impossible : … »).
  - `get_json(url: str, *, opener: Opener | None = None, timeout: float = 30.0) -> object` (même politique d'erreurs).

- [ ] **Step 1 : tests qui échouent** : `test_download_writes_then_renames`, `test_failed_download_leaves_no_file` (opener qui lève au milieu de la lecture), `test_max_bytes_aborts`, `test_http_error_becomes_source_error` (`HTTPError` 500 et 429), `test_user_agent_sent`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): add a safe HTTP download helper`.

---

### Task 4 : lecture de DicoTopo et index local

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/dicotopo/__init__.py`, `sources/dicotopo/index.py`
- Create: `atelier/tests/fixtures/dicotopo/DT62.xml`, `DT59.xml` (synthétiques, première ligne : commentaire « Extrait synthétique pour les tests, aucune donnée DicoTopo »)
- Modify: `atelier/src/prosopo_gw_atelier/refdata/loader.py`
- Test: `atelier/tests/sources/test_dicotopo_index.py`, `atelier/tests/refdata/test_loader.py`

**Interfaces:**
- Produces:
  - `RefData.current_of(insee: str) -> tuple[Commune, Former | None] | None` : un code actuel rend `(commune, None)` ; un ancien code (2011 ou avant) rend `(commune actuelle, ancienne commune)` ; inconnu → `None`. Cas d'Hesdin et Hesdin-la-Forêt (code partagé `62447`) : la commune actuelle est rendue, l'ancienne commune est choisie par le nom si `name` est passé (`current_of(insee, name=None)`).
  - `@dataclass(frozen=True) class Article: id: str; department: str; headword: str; insee: str | None; commune_insee: str | None; kind: str | None; forms: tuple[str, ...]` (`insee` : code propre d'un article de commune ; `commune_insee` : code de la `localisation` ; `kind` : premier mot de la définition parmi `hameau`, `ferme`, `ecart`, `lieu-dit`, `chateau`, `moulin`, `paroisse`, `abbaye`, `section`, sinon `None`).
  - `parse_dicotopo(path: Path) -> Iterator[Article]` (`iterparse`, élément par élément, mémoire bornée) ; `skipped` compté par une variante `parse_with_stats(path) -> tuple[list[Article], int]`.
  - `class DicoTopoIndex(path: Path)` : `add_department(department: str, xml: Path, downloaded_at: str) -> tuple[int, int]` (articles indexés, ignorés ; remplace le département dans une transaction) ; `departments() -> dict[str, str]` (département → date) ; `lookup(key: str, department: str) -> list[Article]` ; `get(article_id: str) -> Article | None` ; `remove(department: str)`.
  - Index : tables `articles(id PRIMARY KEY, department, headword, insee, commune_insee, kind)`, `forms(key, article_id)` avec index sur `(key)`, `departments(department PRIMARY KEY, downloaded_at, articles, skipped)`. Clé de forme : `name_key` de `places/cluster.py` après retrait de la ponctuation finale (`Marconne,` → `marconne`) et des italiques.

- [ ] **Step 1 : relever la structure réelle.** Télécharger un `DTxx.xml` réel dans le scratchpad (hors dépôt), relever : balises de l'article (`article@id`, `vedette`, `definition`, `localisation/commune@insee`, `forme_ancienne/i`, code INSEE propre d'un article de commune), et l'encodage. Reporter la structure (pas le contenu) dans la docstring de `index.py`. Écrire les fixtures synthétiques avec cette structure : dans `DT62.xml`, un article de commune `Hesdin-la-Forêt` (62447), un hameau inventé `Marconne` rattaché à 62447 avec deux formes anciennes inventées, deux lieux-dits homonymes inventés (`Le Quesnoy-Fictif`) sur deux communes, un article sans vedette, un article sans aucun code ; dans `DT59.xml`, un lieu-dit rattaché au code 2011 d'une commune fusionnée depuis dans `refdata_mini` (Lomme → Lille).
- [ ] **Step 2 : tests qui échouent** : `test_parse_articles` (identifiants, formes, `commune_insee`), `test_malformed_articles_are_skipped` (2 ignorés), `test_lookup_by_form_and_department`, `test_reindex_replaces_department`, `test_current_of_former_code_2011` (code de Lomme → Lille + ancienne commune Lomme), `test_current_of_shared_code_uses_name`.
- [ ] **Step 3 : lancer** → échec. **Step 4 : implémenter.** **Step 5 : relancer** → PASS.
- [ ] **Step 6 : commit** `feat(atelier): parse and index DicoTopo department files locally` (vérifier avec `git diff --cached --name-only` qu'aucun vrai `DTxx.xml` n'est indexé).

---

### Task 5 : téléchargement d'un département DicoTopo par la file

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/dicotopo/download.py`
- Test: `atelier/tests/sources/test_dicotopo_download.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 4.
- Produces:
  - `RAW_URL = "https://raw.githubusercontent.com/chartes/dico-topo/<branche>/data/DT{dept}/DT{dept}.xml"` et `CONTENTS_URL` (choix 10) ; la Task vérifie la branche et le motif.
  - `coverage(cache: Path, *, refresh: bool = False, opener: Opener | None = None) -> list[str]` (départements couverts, `["01", "02", …]`).
  - `request_download(queue: SourceQueue, departments: Iterable[str]) -> list[int]` (tâches `download`, priorité 0, clé `DTxx`).
  - `handle_download(job: Job, *, cache: Path, opener: Opener | None = None) -> None` : télécharge `cache/dicotopo/DTxx.xml` puis met en file la tâche `index`.
  - `handle_index(job: Job, *, cache: Path, index: DicoTopoIndex) -> None` : indexe ; un fichier absent ou `.part` → `SourceError`.
  - `remove_department(cache: Path, index: DicoTopoIndex, department: str) -> None`.

- [ ] **Step 1 : tests qui échouent** (opener factice qui sert les fixtures) : `test_download_then_index_through_worker`, `test_partial_download_is_never_indexed`, `test_coverage_cached_without_network` (deuxième appel sans opener), `test_unknown_department_is_refused` (`"20"` ou `"999"` → `SourceError` avant toute requête), `test_remove_department`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): download and index DicoTopo departments on demand`.

---

### Task 6 : source DicoTopo (local, API) et règles de proposition

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/dicotopo/source.py`
- Test: `atelier/tests/sources/test_dicotopo_source.py`

**Interfaces:**
- Consumes: Tasks 2 à 5 ; `RefData.current_of` ; `Level`, `Decomposition`.
- Produces:
  - `DICOTOPO = "dicotopo"` ; `API_URL = "https://dicotopo.cths.fr/api/1.0/"` ; `article_link(identifier: str) -> str`.
  - `class DicoTopoSource(index: DicoTopoIndex, ref: RefData, *, api_enabled: bool, opener: Opener | None = None, limiter: RateLimiter | None = None)` qui implémente `Source` : `search` lit l'index, puis l'API seulement si `api_enabled` et si le département n'est pas indexé ; les candidats portent `parents` déjà ramenés au COG actuel (`commune_historique` éventuelle avec sa `nature`, `commune` origine `insee`).
  - `queries_for(levels: Sequence[Level], decomposition: Decomposition) -> list[LevelQuery]` : choix 7 (un niveau non reconnu sous une commune résolue ; ou l'écriture sans commune résolue, avec son département).
  - `proposals(levels: Sequence[Level], candidates: Sequence[SourceCandidate]) -> tuple[tuple[Level, ...], tuple[tuple[Level, ...], ...]]` : la chaîne avec ses niveaux proposés (`origin="dicotopo"`, `status="proposed"`, `identifier`, `source` du choix 9) et les alternatives ; règles du choix 7.

- [ ] **Step 1 : vérifier l'API** (navigateur ou `curl` hors tests) : recherche par libellé et département, lecture d'un article, motif du lien public d'un article. Noter les URLs dans la docstring. Si la recherche n'existe pas, l'API ne sert qu'à `article()`, et le rapport le dit.
- [ ] **Step 2 : tests qui échouent**

```python
def test_hamlet_under_resolved_commune(source, ref):
    levels = rule_levels(decompose("Marconne, Hesdin-la-Forêt", ref), ref)
    chain, alternatives = proposals(levels, search_all(source, levels))
    marconne = chain[0]
    assert (marconne.type, marconne.origin, marconne.status) == ("lieu_dit", "dicotopo", "proposed")
    assert marconne.identifier.startswith("P") and "dicotopo.cths.fr" in marconne.source
    assert alternatives == ()

def test_ancient_form_without_commune(source, ref): ...       # forme ancienne inventée de Marconne → lieu_dit + commune 62447 (origine insee)
def test_insee_2011_brought_to_current_commune(source, ref): ...  # DT59 : lieu-dit de Lomme → commune Lille + commune_historique Lomme
def test_never_changes_resolved_commune(source, ref): ...    # article d'une autre commune → aucune proposition
def test_homonyms_give_alternatives(source, ref): ...
def test_api_used_only_when_enabled_and_not_indexed(source_factory): ...  # opener factice compte les appels
def test_api_error_is_recorded(source_factory): ...          # 500 → SourceError, rien en cache
```

- [ ] **Step 3 : lancer** → échec. **Step 4 : implémenter.** **Step 5 : relancer** → PASS.
- [ ] **Step 6 : commit** `feat(atelier): propose hamlets and ancient names from DicoTopo`.

---

### Task 7 : refus mémorisés et propositions superposées dans le projet

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/store/schema.sql`, `store/registry.py`, `store/exchange.py`, `atelier/src/prosopo_gw_atelier/project.py`
- Test: `atelier/tests/store/test_registry.py`, `test_exchange.py`, `atelier/tests/test_project.py`

**Interfaces:**
- Consumes: Tasks 2, 6.
- Produces:
  - `SCHEMA_VERSION = 4` ; table `refused_proposals(subject TEXT, source TEXT, identifier TEXT, project TEXT, decided_at TEXT, PRIMARY KEY (subject, source, identifier))` dans `_TABLES`.
  - `PlaceRegistry.refuse_source_proposal(subject: str, source: str, identifier: str, project: str) -> int | None` ; `PlaceRegistry.refused(subject: str) -> set[tuple[str, str]]` ; `PlaceRegistry.add_level(place_id: str, level: Level, project: str) -> int | None` (insère un niveau validé à son rang et renumérote ; journal `correct`).
  - Échange : `propositions_refusees` (`sujet`, `source`, `identifiant`) facultative.
  - `Project.attach_sources(queue: SourceQueue, sources: Mapping[str, Source]) -> None` : à l'ouverture et au rechargement, met en file une tâche `match` par requête des clusters (priorité : nombre d'occurrences) dont le résultat n'est pas en cache ; `Project.touch(cluster_id)` relève la priorité des requêtes du cluster ouvert.
  - `ClusterView.levels` inclut les propositions superposées (sauf refusées : sujet `place:` pour un lieu, `writing:` de chacune des écritures sinon) ; `ClusterView.alternatives` gagne celles des sources ; `ClusterView.pending_sources: tuple[str, ...]` (sources dont un résultat est attendu).
  - `handle_match(job: Job, *, source: Source, queue: SourceQueue) -> None` : exécute `search` et stocke le résultat (liste vide comprise).

- [ ] **Step 1 : tests qui échouent** : `test_refuse_then_undo`, `test_schema3_file_upgraded_to_4`, `test_export_import_refused_proposals`, `test_add_level_renumbers`, `test_project_overlays_dicotopo_proposal` (fixture `.gw` synthétique avec `Marconne, Hesdin-la-Forêt`, source sur l'index de test, `Worker.run_once` jusqu'à vider la file), `test_refused_proposal_stays_refused` (refus, rechargement, `queue.clear("dicotopo")`, nouveau passage : absente), `test_opened_cluster_is_matched_first`, `test_overlay_does_not_write_registry` (journal inchangé après passage de la file).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer la suite** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): overlay source proposals and remember refusals`.

---

### Task 8 : API Sources et fil de fond

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/web/app.py`, `web/schemas.py`, `atelier/src/prosopo_gw_atelier/cli.py`
- Test: `atelier/tests/web/test_api.py`, `atelier/tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1 à 7.
- Produces:
  - `create_app(project, registry, ref, *, sources: SourceRuntime | None = None, start_worker: bool = True)` ; `SourceRuntime` (dans `sources/__init__.py`) regroupe `queue`, `config`, `sources`, `index` et construit les gestionnaires du `Worker`. Le fil démarre au démarrage de l'application et s'arrête à sa fermeture (`lifespan`).
  - `GET /api/sources` → `{"dicotopo": {"coverage": [...], "departments": [{"code", "name", "downloaded_at", "articles", "skipped"}], "api_enabled": bool}, "queue": {"counts": ..., "errors": [{"source", "kind", "key", "error", "attempts"}]}, "attributions": [str]}`.
  - `POST /api/sources/dicotopo/download` `{"departments": ["62"]}` ; `DELETE /api/sources/dicotopo/departments/{code}` ; `PUT /api/sources/dicotopo/api` `{"enabled": bool}` (écrit `config.json`) ; `POST /api/sources/queue/retry` ; `POST /api/sources/cache/clear` `{"source": "dicotopo"}`.
  - `GET /api/clusters/{id}` appelle `project.touch(id)`.
  - `POST /api/places/{place_id}/source-proposals/accept` `{level}` → `add_level` ; `POST /api/source-proposals/refuse` `{subject, source, identifier}`.
  - Messages d'erreur en français, 400 pour un département inconnu.

- [ ] **Step 1 : tests qui échouent** : `test_sources_status`, `test_request_download_enqueues`, `test_toggle_api_writes_config`, `test_unknown_department_400`, `test_accept_source_proposal_on_place_then_undo`, `test_refuse_source_proposal`, `test_cluster_view_bumps_priority`, `test_worker_not_started_in_tests` ; `test_cli` : le lanceur factice reçoit une application dont le fil démarre et s'arrête.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): add the sources API and run the queue in the background`.

---

### Task 9 : écran Sources et propositions DicoTopo

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/web/static/app.js`, `style.css`, `index.html`
- Test: `atelier/tests/web/test_static.py`

Écran : onglet « Sources ». Section DicoTopo : départements couverts (code et nom), téléchargés (date, articles, ignorés), case par département et bouton « Télécharger » ; bouton « Retirer » par département ; interrupteur « Interroger l'API DicoTopo en dernier recours » ; mention de licence (« CC BY-NC-ND 3.0 FR : données gardées sur cet ordinateur, jamais exportées en dehors des identifiants »). Section File : compteurs par état, progression, dernières erreurs, « Relancer les échecs ». Section Cache : « Vider le cache DicoTopo ». Attributions. Rafraîchissement toutes les 3 s tant que des tâches sont en cours, sans redessiner la liste des lieux.

Détail d'un cluster : une proposition `dicotopo` affiche « proposé (DicoTopo) », un lien vers l'article, « Accepter » et « Refuser » ; les alternatives DicoTopo s'affichent comme celles de l'étape 1 ; « recherche en cours » quand `pending_sources` n'est pas vide.

- [ ] **Step 1 : tests qui échouent** : `test_sources_tab_present` (chaînes « Sources », « Télécharger », « CC BY-NC-ND », `/api/sources`, « Relancer les échecs »).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : vérifier à la main** avec les fixtures servies par un faux serveur local (`python -m http.server` dans le scratchpad, URL passée par la variable `PROSOPO_GW_ATELIER_DICOTOPO_RAW`, lue seulement si définie) : télécharger le 62 synthétique, voir la proposition sur `Marconne, Hesdin-la-Forêt`, l'accepter, annuler, la refuser. Noter le résultat dans le rapport.
- [ ] **Step 6 : commit** `feat(atelier): add the sources screen and DicoTopo proposals`.

---

### Task 10 : export et documentation

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/export/pivot.py`, `export/LISEZMOI.txt`, `export/archive.py`, `atelier/README.md`, `docs/reflexions/points-ouverts.md`
- Test: `atelier/tests/export/test_pivot.py`, `test_archive.py`

**Interfaces:**
- Consumes: niveaux validés d'origine `dicotopo` ; `DicoTopoIndex.departments()`.
- Produces : `niveaux_lieux` exporte `origine = dicotopo`, `identifiant = P…`, `source` du choix 9 ; `LISEZMOI` cite DicoTopo (CTHS, École nationale des chartes), la licence CC BY-NC-ND 3.0 FR, les départements utilisés et leur date de téléchargement, uniquement si un niveau `dicotopo` est exporté.

- [ ] **Step 1 : tests qui échouent** : `test_dicotopo_level_exported_with_link`, `test_no_ancient_form_in_export` (aucune forme ancienne de la fixture dans aucun fichier de l'archive), `test_readme_cites_dicotopo_only_when_used`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : documenter** : README (sources externes, activation, cache, licences, où vivent les fichiers), points ouverts (API non vérifiée si c'est le cas, couverture de 52 départements environ).
- [ ] **Step 6 : lancer toute la suite, ruff, mypy** → tout passe.
- [ ] **Step 7 : commit** `feat(atelier): export DicoTopo levels with their attribution` puis `docs(atelier): describe external sources and DicoTopo`.
