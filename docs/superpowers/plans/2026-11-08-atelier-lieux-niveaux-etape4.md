# Atelier : lieux étrangers et GeoNames (étape 4), plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** proposer, pour les pays que l'utilisateur choisit, le type des niveaux étrangers, les niveaux manquants et l'identifiant GeoNames, à partir de fichiers GeoNames téléchargés par pays, avec l'API en dernier recours ; écran Pays et correction lieu par lieu.

**Architecture :** GeoNames est une deuxième `Source` (interface, file et cache de l'étape 3). Ses fichiers par pays sont téléchargés dans le cache et indexés en SQLite. Le réglage par pays et la correction par écriture vivent dans le référentiel personnel (schéma 5) ; le projet ne met en file les recherches GeoNames que pour les clusters dont le mode effectif est « proposer avec GeoNames ». Les résultats sont superposés comme propositions, comme ceux de DicoTopo.

**Tech Stack :** Python ≥ 3.11, workspace `uv`, SQLite, `zipfile`, `csv`, `urllib.request`, FastAPI + Pydantic, JavaScript sans framework, pytest, ruff, mypy strict. Aucune nouvelle dépendance.

**Spec :** `docs/superpowers/specs/2026-11-08-atelier-lieux-niveaux-design.md` (§ 3 licences, 4.2, 8, 9 « Écran Pays » et « Écran Sources », 10, 11 `LISEZMOI`, 13 étape 4, 15 « GeoNames »). Prérequis : étape 3 dans `main` (`Source`, `SourceQueue`, `fetch`, `LocalConfig`, superposition des propositions, `refused_proposals`).

## Global Constraints

- Dépôt **public** : fixtures synthétiques uniquement (petits fichiers au format GeoNames, lieux réels permis, identifiants et populations inventés) ; jamais de `*.gw`/`*.ged` réel ; ne jamais lire `_local_testdata/bases/`.
- **L'identifiant GeoNames de l'utilisateur** vit dans `config.json` (local, `0600`) **uniquement** : jamais dans le dépôt, le référentiel, un export, un message d'erreur, un journal ou un fichier de cache.
- Aucune requête réseau dans les tests (fixture `no_network` de l'étape 3).
- **Par défaut, l'atelier garde ce qui est écrit.** Pays normalisé comme en v1. GeoNames ne fait que **proposer** ; en cas de désaccord, ce qui est écrit reste affiché à côté ; un niveau écrit que GeoNames ne connaît pas (Prusse, Bohême) reste tel quel.
- Le réglage d'un pays suit l'utilisateur d'un projet à l'autre ; la correction d'un lieu **reste valable** si le réglage du pays change.
- `git add` avec chemins explicites, puis `git diff --cached --name-only` ; ni `git push`, ni `--force`, ni étiquette sans accord explicite. Branche `feat/atelier-geonames`.
- `uv` exclusivement ; mêmes commandes de tests, lint et types. Code et commits en anglais (avec `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`), textes affichés et documentation en français. `core` non modifié.

## Choix de ce plan (à relire)

1. **Clé d'un pays : le code ISO alpha-2.** Le COG des pays (`v_pays_territoire`) porte `CODEISO2` ; `pays.csv.gz` gagne une colonne `iso2` et `RefData.country_iso(name) -> str | None`. Un pays sans code (historique : Prusse) n'apparaît pas à l'écran Pays avec un choix, seulement comme « tel qu'écrit ».
2. **Correction lieu par lieu, par écriture.** Table `source_overrides(writing, source, mode, project, decided_at)` ; corriger un cluster écrit une ligne par écriture du cluster. L'écriture étant la clé stable du référentiel, la correction survit à la validation, au rechargement et au changement de réglage du pays. Mode effectif d'un cluster : la correction si **toutes** ses écritures en ont une identique, sinon le réglage du pays (une correction partielle est signalée à l'écran).
3. **Réglage par pays** : table `country_settings(country TEXT PRIMARY KEY, mode TEXT CHECK (mode IN ('written', 'geonames')), project, decided_at)` ; absence = `written`. Schéma 5, montée générique. Journal : action `correct`, charges `{"kind": "country_setting", …}` et `{"kind": "source_override", …}`. Export JSON du référentiel : listes facultatives `reglages_pays` et `corrections_sources`.
4. **Fichiers** : `https://download.geonames.org/export/dump/<CC>.zip` (contient `<CC>.txt`), `admin1CodesASCII.txt`, `admin2Codes.txt`, `countryInfo.txt`. Un pays passé à `geonames` déclenche le téléchargement de son fichier et, si absents, des trois tables communes. `cities500.zip` n'est **pas** utilisé dans cette étape (les fichiers par pays le contiennent). La Task 3 vérifie noms, licence (CC BY 4.0 attendue) et tailles, et l'écran affiche la taille avant téléchargement quand elle est connue (`Content-Length` d'une requête `HEAD`).
5. **Index** : `cache/geonames/<CC>.sqlite`, entités des classes `P` (lieux habités) et `A` (divisions administratives) seulement ; noms : `name`, `asciiname` et `alternatenames` (sans les codes postaux, liens et codes aéroports : entrées de moins de 2 lettres, avec un chiffre ou commençant par `http`). Le fichier `.txt` brut est supprimé après indexation, le `.zip` gardé jusqu'au vidage du cache.
6. **Types proposés** (codes de fonction GeoNames → `FOREIGN_TYPES` de l'étape 1) : `PPL*` → `localite` ; `ADM1` et `ADM2` par pays, table `ADMIN_TYPES` : `CA` province / —, `US` etat / comte, `GB` nation_constitutive / comte, `IE` province / comte, `RU`, `UA`, `BY`, `KZ` oblast / district, `CH` canton / district, `DE`, `AT` etat / district, `BE`, `NL`, `IT`, `ES` province (ADM2) ; ailleurs le niveau est proposé **sans type** (seulement l'identifiant). La table est un dictionnaire dans `sources/geonames/types.py`, facile à compléter.
7. **Lecture d'un cluster étranger** : le niveau 0 est cherché comme `PPL*` (puis `ADM*` s'il n'y a aucun lieu habité) dans le pays ; les candidats sont filtrés par les niveaux écrits au-dessus (un niveau écrit qui a la clé du nom de l'`ADM1` ou de l'`ADM2` du candidat le confirme). Un seul candidat restant → propositions ; plusieurs → le plus peuplé n'est **pas** choisi : alternatives (au plus 5, triées par population) ; aucun → rien.
8. **Propositions** pour un candidat retenu : `identifier = "<geonameid>"`, `source = "GeoNames <date d'extraction du fichier>"`, `origin = "geonames"`, coordonnées du candidat sur le niveau 0 ; type proposé sur chaque niveau écrit qui correspond à l'`ADM1` / `ADM2` ; niveau `ADM1` / `ADM2` manquant ajouté comme proposé, à sa place (entre le niveau qu'il contient et celui qui le contient) ; un niveau écrit qui ne correspond à rien reste tel quel, à sa place. Si le nom GeoNames diffère du nom écrit d'un niveau confirmé, le nom écrit reste et le nom GeoNames va dans la proposition, affichée à côté.
9. **Proposer un type sur un niveau écrit** : la proposition est un niveau `status="proposed"` de même nom et rang que le niveau écrit, que l'écran montre comme « type proposé : province » avec Accepter / Refuser ; accepter remplace le niveau écrit par sa version typée (même chemin que l'étape 3 : chaîne en cours d'édition, ou `add_level`/`set_levels` pour un lieu validé).
10. **API** (dernier recours) : seulement si `geonames_username` est saisi **et** le pays n'a pas de fichier indexé ou le nom n'y est pas. `https://secure.geonames.org/searchJSON?name_equals=…&country=CC&featureClass=P&featureClass=A&maxRows=10&style=FULL&username=…` et `getJSON?geonameId=…`. Débit : 1 requête toutes les 4 s (1 000 par heure) et 10 000 par jour au plus, compteur journalier gardé dans `cache/geonames/api_counter.json` (date, nombre ; aucun identifiant). Les codes d'erreur GeoNames dans le JSON (`status.value` 18, 19, 20 : plafond atteint) arrêtent les requêtes jusqu'à l'heure ou au jour suivant.

## Review Focus

- **Identifiant GeoNames qui fuit** (message d'erreur avec l'URL, cache des réponses, export, journal) : il n'apparaît nulle part hors de `config.json`. → Task 5 `test_username_never_leaks` (cherche la valeur dans les erreurs, le cache SQLite, l'archive d'export et le référentiel).
- **Plafond de l'API atteint** (réponse 200 avec `status` d'erreur, 429, journée épuisée) : la file s'arrête pour GeoNames jusqu'à la fenêtre suivante, les autres sources continuent, l'écran le dit. → Task 5 `test_api_quota_pauses_geonames_only`.
- **Pays énorme** (`US.zip`, centaines de Mo) : lecture ligne à ligne, insertion par lots, mémoire bornée ; un arrêt pendant l'indexation laisse l'ancien index intact. → Task 2 `test_index_build_is_atomic`.
- **Réglage du pays changé après une correction de lieu** : la correction l'emporte dans les deux sens. → Task 4 `test_override_survives_country_change`.
- **Homonymes dans un même pays** (Springfield, Saint-Jean) sans niveau écrit pour départager : alternatives, jamais le plus peuplé d'office. → Task 6 `test_homonyms_without_parents_give_alternatives`.

---

## Fichiers

| Fichier | Rôle | Tâches |
|---|---|---|
| `atelier/tools/build_refdata.py`, `refdata/data/pays.csv.gz`, `refdata/loader.py` | code ISO des pays | 1 |
| `atelier/tests/fixtures/refdata_sources/`, `refdata_mini/` | colonne `CODEISO2` dans les fixtures | 1 |
| `atelier/src/prosopo_gw_atelier/sources/geonames/index.py` | lecture des fichiers, index SQLite | 2 |
| `atelier/tests/fixtures/geonames/` | `CA.zip`, `GB.zip`, `admin1CodesASCII.txt`, `admin2Codes.txt`, `countryInfo.txt` synthétiques (et leur générateur) | 2 |
| `atelier/src/prosopo_gw_atelier/sources/geonames/download.py` | téléchargement par la file | 3 |
| `atelier/src/prosopo_gw_atelier/store/registry.py`, `schema.sql`, `exchange.py` | réglages par pays, corrections, schéma 5 | 4 |
| `atelier/src/prosopo_gw_atelier/sources/geonames/source.py`, `types.py` | `GeoNamesSource` (local, API), types | 5, 6 |
| `atelier/src/prosopo_gw_atelier/project.py` | mode effectif, file GeoNames, pays du projet | 7 |
| `atelier/src/prosopo_gw_atelier/web/app.py`, `schemas.py` | API Pays, GeoNames dans Sources | 8 |
| `atelier/src/prosopo_gw_atelier/web/static/app.js`, `style.css`, `index.html` | écran Pays, section GeoNames, correction par lieu | 9 |
| `atelier/src/prosopo_gw_atelier/export/pivot.py`, `LISEZMOI.txt`, `archive.py`, `atelier/README.md`, `docs/reflexions/points-ouverts.md` | export, attribution, documentation | 10 |

---

### Task 1 : code ISO des pays

**Files:**
- Modify: `atelier/tools/build_refdata.py` (`read_countries` garde `CODEISO2`), `atelier/src/prosopo_gw_atelier/refdata/loader.py`, `refdata/data/pays.csv.gz` (régénéré avec les sources de `_local_testdata/refdata/`), fixtures `refdata_sources/v_pays_territoire_2026.csv` et `refdata_mini` (régénérés)
- Test: `atelier/tests/refdata/test_build_refdata.py`, `test_loader.py`

**Interfaces:**
- Produces: `pays.csv.gz` en-tête `nom;nom_officiel;iso2` ; `RefData.country_iso(name: str) -> str | None` (nom usuel ou officiel, comme `country`).

- [ ] **Step 1 : tests qui échouent** : `test_country_iso` (`Canada` → `CA`, `Royaume-Uni` → `GB`, `Prusse` → `None`), `test_build_keeps_iso2`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter et régénérer** (`uv run --package prosopo-gw-atelier python atelier/tools/build_refdata.py …`, mêmes sources que l'étape 1 ; vérifier que seul `pays.csv.gz` change). **Step 4 : relancer la suite** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): keep the ISO code of each country`.

---

### Task 2 : lecture des fichiers GeoNames et index par pays

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/geonames/__init__.py`, `sources/geonames/index.py`
- Create: `atelier/tests/fixtures/geonames/make_geonames_mini.py` et ses sorties (synthétiques : `CA.zip` avec Winnipeg, Manitoba et deux lieux homonymes inventés ; `GB.zip` avec Storrington, East Sussex, England ; tables communes réduites à CA et GB)
- Test: `atelier/tests/sources/test_geonames_index.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class GeoPlace: geonameid: int; name: str; feature_class: str; feature_code: str; country: str; admin1: str; admin2: str; population: int; latitude: float; longitude: float`.
  - `read_dump(zip_path: Path, country: str) -> Iterator[GeoPlace]` (19 colonnes séparées par tabulation, classes `P` et `A` seulement) ; noms alternatifs lus par `read_names(zip_path, country) -> Iterator[tuple[int, str]]` (filtre du choix 5).
  - `read_admin_codes(path: Path) -> dict[str, tuple[str, int]]` (`"CA.03"` → (nom, geonameid) ; même lecteur pour `admin2Codes.txt`, clé `"GB.ENG.P5"`) ; `read_country_info(path: Path) -> dict[str, str]` (lignes `#` ignorées ; ISO → nom anglais).
  - `class GeoNamesIndex(directory: Path)` : `build(country: str, zip_path: Path, admin1: Path, admin2: Path, extracted: str) -> int` (écrit `<CC>.sqlite.part` puis renomme : atomique) ; `countries() -> dict[str, str]` (pays → date) ; `lookup(country: str, key: str) -> list[GeoPlace]` ; `get(country: str, geonameid: int) -> GeoPlace | None` ; `admin_name(country: str, admin1: str, admin2: str | None = None) -> tuple[str, int] | None` ; `remove(country: str)`. Clé de nom : `name_key` de l'étape 1.

- [ ] **Step 1 : tests qui échouent** : `test_read_dump_keeps_p_and_a`, `test_alternate_names_filtered` (codes postaux et URL écartés), `test_admin_codes`, `test_lookup_by_name_and_alternate`, `test_index_build_is_atomic` (exception au milieu de `build` : l'ancien `<CC>.sqlite` reste lisible, aucun `.part` gardé), `test_large_file_streams` (fichier généré de 200 000 lignes, mémoire mesurée par `tracemalloc` sous 50 Mo).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter** (insertion par lots de 10 000, `executemany`). **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): read and index GeoNames country files`.

---

### Task 3 : téléchargement des fichiers GeoNames par la file

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/geonames/download.py`
- Test: `atelier/tests/sources/test_geonames_download.py`

**Interfaces:**
- Consumes: étape 3 (`SourceQueue`, `download`, `Opener`) ; Task 2.
- Produces:
  - `DUMP_URL = "https://download.geonames.org/export/dump/"` ; `COMMON_FILES = ("admin1CodesASCII.txt", "admin2Codes.txt", "countryInfo.txt")`.
  - `request_country(queue: SourceQueue, country: str) -> list[int]` (tâches `download` des fichiers communs absents puis du pays ; puis `index`).
  - `handle_download(job, *, cache, opener=None)`, `handle_index(job, *, cache, index)` ; `remote_size(url, *, opener=None) -> int | None` (`HEAD`).
  - `remove_country(cache: Path, index: GeoNamesIndex, country: str) -> None`.

- [ ] **Step 1 : vérifier la source** (hors tests) : noms des fichiers, présence de `<CC>.txt` dans `<CC>.zip`, licence affichée sur `https://download.geonames.org/export/dump/` (attendue : CC BY 4.0), taille de quelques pays. Noter dans la docstring ; corriger le choix 4 si besoin et le dire dans le rapport.
- [ ] **Step 2 : tests qui échouent** (opener factice) : `test_country_download_then_index`, `test_common_files_downloaded_once`, `test_invalid_country_code_refused` (`"XX"`, `"ca"` normalisé en `CA`, `"../"` refusé avant toute requête), `test_remote_size`.
- [ ] **Step 3 : lancer** → échec. **Step 4 : implémenter.** **Step 5 : relancer** → PASS.
- [ ] **Step 6 : commit** `feat(atelier): download GeoNames country files on demand`.

---

### Task 4 : réglages par pays et corrections par écriture (schéma 5)

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/store/schema.sql`, `store/registry.py`, `store/exchange.py`
- Test: `atelier/tests/store/test_registry.py`, `test_exchange.py`

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION = 5` ; tables `country_settings` et `source_overrides(writing TEXT, source TEXT, mode TEXT CHECK (mode IN ('written', 'geonames')), project TEXT, decided_at TEXT, PRIMARY KEY (writing, source))`, dans `_TABLES`.
  - `SourceMode = Literal["written", "geonames"]`.
  - `PlaceRegistry.set_country_mode(country: str, mode: SourceMode, project: str) -> int | None` ; `country_modes() -> dict[str, SourceMode]` ; `set_override(writings: Sequence[str], source: str, mode: SourceMode | None, project: str) -> int | None` (`None` retire la correction ; une seule entrée de journal pour toutes les écritures) ; `overrides(source: str) -> dict[str, SourceMode]`.
  - Échange : `reglages_pays` (`pays`, `mode`) et `corrections_sources` (`ecriture`, `source`, `mode`), facultatives.

- [ ] **Step 1 : tests qui échouent** : `test_country_mode_round_trip_and_undo`, `test_override_on_many_writings_is_one_journal_entry`, `test_override_survives_country_change` (correction `written` sur un cluster, pays passé à `geonames` puis revenu : la correction reste), `test_schema4_file_upgraded_to_5`, `test_export_import_settings`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): store GeoNames settings per country and per writing`.

---

### Task 5 : source GeoNames, mode API

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/geonames/source.py`
- Test: `atelier/tests/sources/test_geonames_api.py`

**Interfaces:**
- Consumes: étape 3 (`Source`, `LevelQuery`, `SourceCandidate`, `RateLimiter`, `get_json`, `LocalConfig`) ; Task 2.
- Produces:
  - `GEONAMES = "geonames"` ; `class GeoNamesSource(index: GeoNamesIndex, *, config: LocalConfig, counter_path: Path, opener: Opener | None = None, limiter: RateLimiter | None = None, clock=time.time)` qui implémente `Source` (`search` : index local, puis API selon le choix 10 ; `article("<id>")` : index puis `getJSON`).
  - `class QuotaReached(SourceError)` portant `retry_at: float` ; la file (étape 3) gagne `SourceQueue.pause(source: str, until: float)` : `next_job` saute les tâches de cette source jusqu'à `until`.
  - Les URL contenant l'identifiant ne sont jamais mises dans un message : `SourceError("GeoNames a refusé la requête (code 19 : plafond horaire)")`.

- [ ] **Step 1 : tests qui échouent** (opener factice qui sert des JSON au format GeoNames) : `test_api_only_with_username`, `test_api_only_when_local_misses`, `test_daily_counter_persists` (10 000 atteint → `QuotaReached` jusqu'à minuit UTC), `test_api_quota_pauses_geonames_only` (réponse `{"status": {"value": 19}}` → tâche GeoNames repoussée, une tâche DicoTopo passe), `test_username_never_leaks` (identifiant factice `user-secret-123` absent des messages d'erreur, de `sources.sqlite`, de `api_counter.json`, du référentiel et d'une archive d'export produite après un passage).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): query the GeoNames API as a last resort`.

---

### Task 6 : propositions GeoNames sur une chaîne étrangère

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/sources/geonames/types.py`
- Modify: `atelier/src/prosopo_gw_atelier/sources/geonames/source.py`
- Test: `atelier/tests/sources/test_geonames_source.py`

**Interfaces:**
- Consumes: Tasks 2, 5 ; `Level`, `rule_levels`.
- Produces:
  - `ADMIN_TYPES: dict[str, tuple[str | None, str | None]]` (choix 6) ; `level_type(feature_code: str, country: str) -> str | None`.
  - `queries_for(levels: Sequence[Level], country_iso: str) -> list[LevelQuery]` (le niveau 0 avec ses parents écrits).
  - `proposals(levels: Sequence[Level], candidates: Sequence[SourceCandidate]) -> tuple[tuple[Level, ...], tuple[tuple[Level, ...], ...]]` : choix 7, 8 et 9 ; même signature que celle de DicoTopo (étape 3) pour que le projet les traite de la même façon.

- [ ] **Step 1 : tests qui échouent** (spec § 15)

```python
def test_winnipeg_gets_types_and_identifier(source, ref):
    levels = rule_levels(decompose("Winnipeg, , , Manitoba, Canada", ref), ref)
    chain, alternatives = proposals(levels, search_all(source, levels, "CA"))
    by_name = {l.name: l for l in chain if l.status == "proposed"}
    assert by_name["Winnipeg"].type == "localite" and by_name["Winnipeg"].identifier.isdigit()
    assert by_name["Manitoba"].type == "province"
    assert [l.name for l in chain if l.status == "validated"] == [l.name for l in levels]  # rien d'écrasé

def test_storrington_keeps_four_levels_and_adds_types(source, ref): ...   # East Sussex comte, England nation_constitutive
def test_missing_province_is_added(source, ref): ...                     # "Winnipeg, Canada" → Manitoba proposé, entre les deux
def test_unknown_written_level_stays(source, ref): ...                    # "Winnipeg, Prusse-Fictive, Canada" : niveau gardé, sans proposition
def test_written_name_differs_from_geonames(source, ref): ...             # nom écrit gardé, nom GeoNames dans la proposition
def test_homonyms_without_parents_give_alternatives(source, ref): ...
def test_parents_disambiguate_homonyms(source, ref): ...
def test_country_without_admin_types_gets_identifier_only(source, ref): ...
```

- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): propose level types and missing levels from GeoNames`.

---

### Task 7 : le projet applique le mode GeoNames

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/project.py`
- Test: `atelier/tests/test_project.py` (fixture `.gw` synthétique avec des personnes fictives à `Winnipeg, , , Manitoba, Canada`, `Storrington, , East Sussex, England, Royaume-Uni`, `Königsberg, Prusse`)

**Interfaces:**
- Consumes: Tasks 4, 6 ; étape 3 (`attach_sources`, superposition, `refused`).
- Produces:
  - `@dataclass(frozen=True) class CountryRow: iso: str | None; name: str; writings: int; occurrences: int; mode: SourceMode; downloaded: str | None; overrides: int`.
  - `Project.countries() -> list[CountryRow]` (pays étrangers du projet, triés par écritures décroissantes ; la France exclue).
  - `Project.effective_mode(cluster_id: str) -> tuple[SourceMode, Literal["country", "override", "partial"]]` (choix 2).
  - La file ne reçoit des tâches `match` GeoNames que pour les clusters en mode `geonames` ; un changement de réglage ou de correction met en file les clusters devenus `geonames` et retire (masque) les propositions des clusters revenus à `written`, sans vider leurs résultats en cache.
  - `ClusterView.geonames_mode` et `geonames_mode_origin`.

- [ ] **Step 1 : tests qui échouent** : `test_countries_of_project`, `test_written_mode_has_no_geonames_proposal`, `test_switching_country_enqueues_matches`, `test_override_flips_one_cluster` (et survit au changement du pays), `test_historical_country_has_no_choice` (`Prusse` : `iso is None`, mode `written`).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer la suite** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): apply the GeoNames mode per country and per place`.

---

### Task 8 : API Pays et GeoNames dans Sources

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/web/app.py`, `web/schemas.py`, `sources/__init__.py` (`SourceRuntime` gagne GeoNames)
- Test: `atelier/tests/web/test_api.py`

**Interfaces:**
- Produces:
  - `GET /api/countries` → `{"countries": [CountryRowOut]}` ; `PUT /api/countries/{iso}` `{"mode": "written" | "geonames"}` (passer à `geonames` met en file le téléchargement si le pays n'est pas indexé ; la réponse donne la taille annoncée quand elle est connue).
  - `PUT /api/clusters/{id}/geonames` `{"mode": "written" | "geonames" | null}` (correction par écriture ; `null` la retire).
  - `GET /api/sources` gagne `"geonames": {"countries": [{"iso", "name", "downloaded_at", "size"}], "username_set": bool, "api": {"today": int, "paused_until": str | null}}` ; **jamais** la valeur de l'identifiant.
  - `PUT /api/sources/geonames/username` `{"username": str | null}` (écrit `config.json` ; 400 si la valeur contient autre chose que lettres, chiffres, `_`, `-`, `.`) ; `DELETE /api/sources/geonames/countries/{iso}`.

- [ ] **Step 1 : tests qui échouent** : `test_list_countries`, `test_set_country_mode_enqueues_download`, `test_cluster_override_then_undo`, `test_username_is_write_only` (le `GET` ne renvoie que `username_set`), `test_invalid_username_400`, `test_invalid_country_400`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): add the countries API and GeoNames settings`.

---

### Task 9 : écran Pays, section GeoNames, correction par lieu

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/web/static/app.js`, `style.css`, `index.html`
- Test: `atelier/tests/web/test_static.py`

Écran « Pays » : un tableau des pays du projet (nom, écritures, occurrences, mode, fichier téléchargé ou non, corrections), et pour chacun le choix « Garder tel qu'écrit » / « Proposer avec GeoNames » ; la taille du fichier est rappelée avant le premier téléchargement ; un pays sans code ISO affiche « tel qu'écrit (pays historique) ».

Écran « Sources » : section GeoNames (pays téléchargés, date, taille, « Retirer » ; champ « Identifiant GeoNames » en saisie seule, avec « Identifiant enregistré » quand il l'est et « Effacer » ; compteur de requêtes du jour ; pause en cours) ; attribution « GeoNames, CC BY 4.0 ».

Détail d'un cluster étranger : le mode effectif et son origine (« réglage du pays », « corrigé pour ce lieu », « corrigé pour une partie des écritures »), le bouton inverse (« Garder tel qu'écrit pour ce lieu » / « Proposer avec GeoNames pour ce lieu ») et « Revenir au réglage du pays » ; une proposition de type s'affiche « type proposé : province (GeoNames) » à côté du niveau écrit.

- [ ] **Step 1 : tests qui échouent** : `test_countries_tab_present` (« Pays », « Proposer avec GeoNames », « Garder tel qu'écrit », « Revenir au réglage du pays », « Identifiant GeoNames », « CC BY 4.0 », `/api/countries`).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : vérifier à la main** avec les fixtures servies par un faux serveur local (variable `PROSOPO_GW_ATELIER_GEONAMES_DUMP`, lue seulement si définie) : passer le Canada à GeoNames, voir les propositions sur Winnipeg, en accepter une, corriger un lieu, changer le réglage du pays, vérifier que la correction reste. Noter le résultat dans le rapport.
- [ ] **Step 6 : commit** `feat(atelier): add the countries screen and GeoNames settings`.

---

### Task 10 : export et documentation

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/export/pivot.py`, `export/LISEZMOI.txt`, `export/archive.py`, `atelier/README.md`, `atelier/doc/design_v1.md`, `docs/reflexions/points-ouverts.md`
- Test: `atelier/tests/export/test_pivot.py`, `test_archive.py`

**Interfaces:**
- Produces : `niveaux_lieux` exporte `origine = geonames`, `identifiant = <geonameid>`, `source = GeoNames <date>`, coordonnées ; `lieux.latitude/longitude` reprennent celles du niveau le plus précis qui en a (règle de l'étape 1) ; `LISEZMOI` cite GeoNames (CC BY 4.0, pays utilisés et date de téléchargement) seulement si un niveau `geonames` est exporté.

- [ ] **Step 1 : tests qui échouent** : `test_geonames_level_exported`, `test_place_coordinates_from_geonames_level`, `test_readme_cites_geonames_only_when_used`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : documenter** : README (écran Pays, identifiant GeoNames et où il est gardé, tailles des fichiers, licence), `design_v1.md` (renvoi), points ouverts (types `ADM1`/`ADM2` par pays à compléter, `cities500` non utilisé).
- [ ] **Step 6 : lancer toute la suite, ruff, mypy** → tout passe.
- [ ] **Step 7 : commits** `feat(atelier): export GeoNames levels with their attribution` puis `docs(atelier): describe the countries screen and GeoNames`.
