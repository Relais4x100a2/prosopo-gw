# Exports, étape 1 : tables, rendus et zip — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** produire, depuis une `Genealogy` et l'index des candidates, l'archive `prosopo-<base>-<date>.zip` (tables en CSV, JSON et SQLite, dictionnaire, LISEZMOI, compagnon), sans route ni bouton.

**Architecture:** une définition unique des tables (`formats/tables.py`) porte colonnes, types et lignes ; des rendus génériques (`formats/table_writers.py`) en tirent CSV, JSON, SQLite, dictionnaire et zip. Les tables d'organisations, qui dépendent de l'index des candidates, sont construites côté API (`api/services/organization_tables.py`), et `api/services/export_bundle.py` assemble l'archive. `formats/` n'importe jamais `api/`.

**Tech Stack:** Python ≥ 3.8 (paquet `core`), bibliothèque standard seulement (`csv`, `json`, `sqlite3`, `zipfile`, `hashlib`, `tempfile`), pytest.

**Spec:** `core/doc/exports_design.md` (§ 3, 4, 5, 9, 10). Hors étape : table `pistes` (§ 6, étape 2), route et webapp (§ 5.3 dernière puce, § 7, étape 3).

## Global Constraints

- Aucune donnée réelle : fixtures synthétiques uniquement (`DUPONT Jean`, `MARTIN Marie`…), y compris dans les messages de commit.
- Aucune dépendance ajoutée ; `formats/` n'importe rien de `geneweb_py.api`.
- mypy 0 erreur (`uv run --package geneweb-py mypy core/src/geneweb_py` depuis la racine), types annotés partout, pas de `# type: ignore`.
- Couverture ≥ 80 % ; ruff : `uv run ruff check src tests --ignore E501` et `uv run ruff format src tests` depuis `core/`.
- Tests : `COLUMNS=200 uv run python -m pytest -q` depuis `core/`.
- Noms de colonnes en français, sans accents, en `snake_case`. Une ligne par chose.
- Dates : `<x>_date` = `Date.raw_text` si présent, sinon `str(date)` ; `<x>_annee` = `Date.sort_year()` ; vides (`None`) sans date.
- Identifiants : personne = clé de `Genealogy.persons` ; famille = clé de `Genealogy.families` ; événement personnel = `event_ref(person_id, index)` (`pevt:<id>:<i>`) ; événement familial = `fevt:<famille_id>:<i>` ; index = position dans `person.events` / `family.events`.
- Commits : `type(scope): message` en anglais, terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` ; `git add` par chemins explicites.

## Review Focus

1. Note ou texte commençant par `=`, `+`, `-`, `@` : neutralisé (préfixe `'`) en CSV seulement, intact en JSON et SQLite. → Task 4, `test_formula_only_neutralized_in_csv`.
2. Note multiligne contenant `;` et `"` : le CSV se relit avec `csv.reader(delimiter=";")` avec le même nombre de lignes que la table. → Task 4, `test_csv_round_trip_multiline`.
3. Personne sans date ni lieu, famille sans mari : cellules vides (`""` en CSV, `null` en JSON, `NULL` en SQLite), pas d'exception. → Task 1, `test_missing_values_are_none`.
4. Base vide (aucune personne) : zip complet, CSV réduits à l'en-tête, tables SQLite vides. → Task 5, `test_empty_genealogy_bundle`.
5. Nom de fichier accentué ou avec espaces (`ma base été.gw`) : nom d'archive assaini, texte accentué intact dans les trois rendus. → Task 5, `test_archive_name_sanitized` ; Task 4, `test_unicode_survives_all_formats`.

---

### Task 1: Définition des tables et tables de la base

**Files:**
- Create: `src/geneweb_py/formats/tables.py`
- Test: `tests/formats/test_tables.py`

**Interfaces:**
- Produces :
  - `ColumnType = Literal["text", "int", "real", "bool"]`
  - `@dataclass(frozen=True) class Column: name: str; type: ColumnType; description: str`
  - `@dataclass(frozen=True) class TableSpec: name: str; columns: Tuple[Column, ...]; primary_key: Optional[str] = None` avec la propriété `column_names -> List[str]`
  - `Row = Dict[str, Union[str, int, float, bool, None]]` (clés = toutes les colonnes de la spec, dans l'ordre)
  - `@dataclass class Table: spec: TableSpec; rows: List[Row]`
  - `family_event_ref(family_id: str, index: int) -> str` → `"fevt:<family_id>:<index>"`
  - Constantes `PERSONNES, FAMILLES, ENFANTS, EVENEMENTS, TEMOINS: TableSpec`
  - `build_base_tables(genealogy: Genealogy) -> List[Table]` dans l'ordre personnes, familles, enfants, evenements, temoins (sources ajoutée en Task 2)
  - `EVENT_TYPE_LABELS: Dict[str, str]`

Colonnes (type entre parenthèses, `text` par défaut ; la description, une phrase en français, est à rédiger pour chaque colonne) :

| Table | PK | Colonnes |
|---|---|---|
| `personnes` | `personne_id` | `personne_id`, `nom`, `prenom`, `occurrence` (int), `sexe` (`M`, `F` ou vide), `naissance_date`, `naissance_annee` (int), `naissance_lieu`, `deces_date`, `deces_annee` (int), `deces_lieu`, `profession`, `note` |
| `familles` | `famille_id` | `famille_id`, `mari_id`, `femme_id`, `mariage_date`, `mariage_annee` (int), `mariage_lieu`, `note` |
| `enfants` | — | `famille_id`, `personne_id`, `rang` (int, 1 pour le premier) |
| `evenements` | `evenement_id` | `evenement_id`, `personne_id`, `famille_id`, `type`, `type_libelle`, `libelle`, `date`, `annee` (int), `lieu`, `ville`, `complement`, `note` |
| `temoins` | — | `evenement_id`, `famille_id`, `personne_id`, `role` |

Règles :
- `note` = notes jointes par `"\n"` (`Person.notes`, `Family.comments`, `Event.notes`), `None` si aucune.
- `evenements` : d'abord les événements personnels (personnes dans l'ordre du dict, puis ordre de `person.events`), puis les familiaux ; `personne_id` vide pour un familial, `famille_id` vide pour un personnel. `type` = `event_type.value`. `type_libelle` = `EVENT_TYPE_LABELS.get(type, type)`. `libelle` = `event_type_raw` avec `_` → espace, `None` si absent. `lieu` = chaîne brute, `ville` = `place_city(lieu)`, `complement` = `parse_place(lieu).complement`.
- `EVENT_TYPE_LABELS` : `birt` Naissance, `bapt` Baptême, `deat` Décès, `buri` Sépulture, `crem` Crémation, `occu` Profession, `resi` Résidence, `educ` Éducation, `grad` Diplôme, `mser` Service militaire, `oth` Autre, `marr` Mariage, `enga` Fiançailles, `div` Divorce, `sep` Séparation, `marc` Contrat de mariage, `pacs` PACS, `other` Autre. Autre code : le code lui-même.
- `temoins` : témoins de famille → `famille_id` rempli, `evenement_id` vide ; témoins d'événement (personnel ou familial) → `evenement_id` rempli, `famille_id` vide. `personne_id` = `witness["person_id"]`. `role` = `WITNESS_KIND_ROLES[kind]` si `witness["witness_kind"]` est un `WitnessKind`, sinon `WITNESS_ROLE` (importés de `core/event_to_organization.py`).

- [ ] **Step 1: Write the failing tests** (fixture : `tests/fixtures/rich_pevt_wit.gw` lue par `GeneWebParser().parse_file`)

```python
def test_table_order_and_columns(): # noms des 5 tables dans l'ordre ; chaque Row a exactement spec.column_names
def test_person_row(): # DUPONT Jean : naissance_annee == 1870, naissance_lieu == "Lyon", deces_annee == 1925, profession / note conformes au fixture
def test_children_rank(): # DUPONT Louis : rang == 1, famille_id == la famille DUPONT Jean + MARTIN Marie
def test_event_ids_and_labels(): # premier événement de DUPONT Jean : evenement_id == event_ref(<id>, 0), type == "birt", type_libelle == "Naissance"
def test_free_event_label(): # "#Cours_peinture" : type == "oth", libelle == "Cours peinture"
def test_family_event(): # marr : evenement_id == "fevt:<famille_id>:0", personne_id is None, ville == "Lyon", complement == "Mairie", note == "Note de mariage"
def test_witness_rows(): # MARTIN Pierre témoin de famille (famille_id rempli, evenement_id None) et témoin de #occu (evenement_id rempli) ; role == "Témoin"
def test_missing_values_are_none(): # parse_string d'une famille "? ? + DUPONT Anne" sans date : mari_id None ou anonyme, mariage_date / mariage_annee None ; personne sans date : naissance_* None
def test_references_resolve(): # tout *_id non vide de enfants, evenements, temoins, familles existe dans la table cible
def test_ids_stable(): # deux appels sur deux parses du même fichier → lignes identiques
```

- [ ] **Step 2: Run** `COLUMNS=200 uv run python -m pytest tests/formats/test_tables.py -q` — Expected: FAIL (module absent).
- [ ] **Step 3: Implement** `formats/tables.py` selon les interfaces et règles ci-dessus.
- [ ] **Step 4: Run** le même test — Expected: PASS ; puis mypy et ruff (Global Constraints).
- [ ] **Step 5: Commit** `feat(exports): define export tables for persons, families and events`

### Task 2: Table `sources`

**Files:**
- Modify: `src/geneweb_py/formats/tables.py`
- Test: `tests/formats/test_tables_sources.py`

**Interfaces:**
- Consumes : `Table`, `TableSpec`, `Column`, `family_event_ref` (Task 1).
- Produces : `SOURCES: TableSpec` (PK `source_id`) ; `build_base_tables` renvoie désormais 6 tables, `sources` en dernier.

Colonnes : `source_id`, `cible` (`personne`, `evenement`, `famille`), `cible_id`, `objet`, `texte`.

Champs lus, dans cet ordre (objet entre parenthèses) : personne — `person_source` (`generale`), `birth_source` (`naissance`), `baptism_source` (`bapteme`), `death_source` (`deces`), `burial_source` (`sepulture`) ; famille — `family_source` (`generale`), `marriage_source` (`mariage`), `common_children_source` (`enfants`) ; événement personnel puis familial — `Event.source` (`evenement`). Texte vide ou blanc ignoré ; texte inchangé sinon.

- `source_id` = `"s-" + sha1(f"{cible}|{cible_id}|{objet}".encode("utf-8")).hexdigest()[:12]`.
- Dédoublonnage : la source d'un événement `birt`, `bapt`, `deat`, `buri` identique au champ correspondant de sa personne (`naissance`, `bapteme`, `deces`, `sepulture`), et celle d'un `marr` identique à `marriage_source` de sa famille, ne produit pas de ligne.

- [ ] **Step 1: Write the failing tests** — fixture inline par `GeneWebParser().parse_string`, avec `#bs`, `#ds`, `#src` sur une personne, `#src` et `#csrc` sur la famille, et un `pevt` avec `#s`. Commencer le test par des assertions sur les champs du modèle (`person.birth_source == ...`) pour vérifier que la syntaxe synthétique est bien lue.

```python
def test_each_source_field_becomes_a_row(): # un (cible, objet, texte) attendu par champ renseigné
def test_event_source_row(): # "#Action-Sociale ... #s Archives" (rich_pevt_wit.gw) → cible "evenement", texte "Archives"
def test_birth_source_not_duplicated(): # birth_source == source de l'événement birt → une seule ligne (cible "personne", objet "naissance")
def test_source_ids_unique_and_stable(): # ids distincts, préfixe "s-", 14 caractères, identiques entre deux parses
def test_blank_source_ignored():
```

- [ ] **Step 2: Run** `COLUMNS=200 uv run python -m pytest tests/formats/test_tables_sources.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `SOURCES` et sa construction dans `build_base_tables` ; adapter `test_table_order_and_columns` (6 tables).
- [ ] **Step 4: Run** `tests/formats/` — Expected: PASS ; mypy, ruff.
- [ ] **Step 5: Commit** `feat(exports): export source texts as a sources table`

### Task 3: Tables d'organisations

**Files:**
- Create: `src/geneweb_py/api/services/organization_tables.py`
- Modify: `src/geneweb_py/api/services/organization_candidates.py` (`UnmatchedEvent` : champ `event_index: int` ajouté en dernier, renseigné dans la boucle de `_unmatched` ; `shared_experience_persons` : clé `"event_index"` ajoutée à chaque dict)
- Test: `tests/api/test_organization_tables.py`

**Interfaces:**
- Consumes : `Column`, `TableSpec`, `Table` (Task 1) ; `CandidateIndex`, `SharedExperienceIndex`, `shared_experience_persons`, `event_ref`, `TYPE_LABELS`, `NAMED_FROM_LABELS`, `SOURCE_LABELS` (existants).
- Produces : `ORGANISATIONS, LIENS, RESTE_A_CLASSER, EXPERIENCES_PROCHES: TableSpec` ; `build_organization_tables(genealogy: Genealogy, index: CandidateIndex, shared: SharedExperienceIndex) -> List[Table]` dans cet ordre.

Colonnes :

| Table | PK | Colonnes |
|---|---|---|
| `organisations` | `organisation_id` | `organisation_id`, `nom`, `type`, `type_libelle`, `lieu`, `source_du_nom`, `mot_declencheur`, `confiance` (real), `a_revoir` (bool), `collectif` (bool), `nb_personnes` (int), `nb_evenements` (int), `premiere_annee` (int), `derniere_annee` (int) |
| `liens` | — | `organisation_id`, `organisation`, `personne_id`, `personne`, `role`, `date`, `annee` (int), `lieu`, `type_evenement`, `type_evenement_libelle`, `evenement_id`, `evenement`, `temoin` (bool), `nb_temoins` (int), `statut`, `nom_retenu` |
| `reste_a_classer` | — | `evenement_id`, `mot` |
| `experiences_proches` | — | `experience_id`, `theme`, `periode`, `lieux`, `raison`, `personne_id`, `personne`, `evenement_id`, `evenement`, `annee`, `lieu` |

Règles :
- Ordre des lignes identique aux CSV actuels (`_sorted(index)`, tri des membres de `links_csv`, ordre de `shared_experiences_csv`).
- `organisations` : `type_libelle` et `source_du_nom` par `TYPE_LABELS` / `NAMED_FROM_LABELS` ; `sources`, `lieux`, `roles` de l'actuel CSV ne sont pas repris (listes, déductibles de `liens`).
- `liens` : `evenement_id` = `member.source_event_id` ; `temoin` = `member.witness` ; `statut` et `nom_retenu` vides (à remplir par l'utilisateur).
- `reste_a_classer` : une ligne par (groupe, événement) de `index.unmatched_groups`, `evenement_id = event_ref(e.person_id, e.event_index)`, `mot = group.word`.
- `experiences_proches` : `periode`, `lieux`, `raison`, `annee` rendus en texte comme dans `shared_experiences_csv` (réutiliser `_years`, `_reason_label`) ; `evenement_id = event_ref(p["person_id"], p["event_index"])`.

- [ ] **Step 1: Write the failing tests** — fixture synthétique produisant au moins une candidate (ex. `fam DUPONT Jean #occu Employé_Banque_Fictive + MARTIN Marie`, cf. `tests/unit/test_occupation_companies.py`), un événement « Autre » non classé et une expérience proche (reprendre une fixture de `tests/api/` qui en produit).

```python
def test_organisation_row(): # nom "Banque Fictive", type "company", type_libelle "Entreprise"
def test_link_row_has_event_id(): # evenement_id commence par "pevt:" et existe dans evenements (build_base_tables)
def test_unmatched_rows(): # une ligne par (mot, événement) ; evenement_id résolu dans evenements
def test_shared_experience_rows_have_ids(): # personne_id et evenement_id résolus
def test_existing_csv_unchanged(): # candidates_csv, links_csv, shared_experiences_csv : sortie identique à avant (pas de régression)
```

- [ ] **Step 2: Run** `COLUMNS=200 uv run python -m pytest tests/api/test_organization_tables.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** toute la suite — Expected: PASS ; mypy, ruff.
- [ ] **Step 5: Commit** `feat(exports): build organization tables with stable event ids`

### Task 4: Rendus CSV, JSON, SQLite et dictionnaire

**Files:**
- Create: `src/geneweb_py/formats/table_writers.py`
- Modify: `src/geneweb_py/api/services/organization_exports.py` (importer `BOM`, `FORMULA_PREFIXES` et la protection contre les formules depuis `table_writers` au lieu de les définir)
- Test: `tests/formats/test_table_writers.py`

**Interfaces:**
- Consumes : `Table`, `TableSpec`, `Column` (Task 1).
- Produces :
  - `BOM`, `FORMULA_PREFIXES`, `neutralize_formula(text: str) -> str`
  - `table_to_csv(table: Table) -> str`
  - `tables_to_json(tables: Sequence[Table], base: str, generated_at: datetime) -> str`
  - `tables_to_sqlite(tables: Sequence[Table]) -> bytes`
  - `dictionary_table(specs: Sequence[TableSpec]) -> Table` (spec `DICTIONNAIRE` : `table`, `colonne`, `type`, `description`)

Rendus :
- CSV : `BOM` + `csv.writer(delimiter=";", lineterminator="\n")` ; en-tête = `column_names` ; `text` → `neutralize_formula`, `int` → `str`, `real` → `f"{v:g}"` avec `.` → `,`, `bool` → `oui`/`non`, `None` → `""`.
- JSON : `{"format": "prosopo-gw/export", "version": 1, "generated_at": <ISO 8601, secondes>, "base": base, "tables": {<nom>: [<Row>, ...]}}`, `ensure_ascii=False`, `indent=2`, valeurs natives.
- SQLite : fichier dans un `tempfile.TemporaryDirectory`, lu en octets ; une table par `Table`, identifiants entre guillemets doubles, types `TEXT`/`INTEGER`/`REAL`/`INTEGER` (bool 0/1), `PRIMARY KEY` sur `primary_key`, `CREATE INDEX` sur chaque autre colonne finissant par `_id` ; insertion par `executemany` paramétré.
- Dictionnaire : une ligne par colonne de chaque spec, `type` rendu `texte`, `entier`, `decimal`, `booleen`.

- [ ] **Step 1: Write the failing tests** (tables construites à la main avec une petite `TableSpec` de test, plus `build_base_tables` sur le fixture)

```python
def test_csv_conventions(): # BOM, ";", "oui"/"non", "0,8", None → ""
def test_formula_only_neutralized_in_csv(): # "=SOMME(A1)" → "'=SOMME(A1)" en CSV ; intact en JSON et SQLite
def test_csv_round_trip_multiline(): # note "a;b\n\"c\"" : csv.reader relit le même nombre de lignes et la même valeur
def test_json_envelope_and_types(): # format, version 1, base, True / 1870 / 0.8 / None natifs
def test_sqlite_tables_and_join(): # sqlite3 sur les octets écrits : mêmes tables, COUNT(*) == len(rows), jointure temoins × personnes non vide
def test_sqlite_primary_key_and_indexes(): # PRAGMA table_info / index_list
def test_parity_across_formats(): # mêmes noms de tables, colonnes et nombres de lignes en CSV, JSON, SQLite
def test_dictionary_covers_every_column():
def test_unicode_survives_all_formats(): # "Éléonore Œuvre" identique dans les trois rendus
```

- [ ] **Step 2: Run** `COLUMNS=200 uv run python -m pytest tests/formats/test_table_writers.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** ; dans `organization_exports.py`, remplacer les définitions locales par les imports, sans changer les sorties.
- [ ] **Step 4: Run** toute la suite — Expected: PASS (dont les tests existants des CSV d'organisations) ; mypy, ruff.
- [ ] **Step 5: Commit** `feat(exports): render tables as CSV, JSON and SQLite`

### Task 5: Archive zip

**Files:**
- Modify: `src/geneweb_py/formats/table_writers.py`
- Create: `src/geneweb_py/api/services/export_bundle.py`
- Test: `tests/api/test_export_bundle.py`

**Interfaces:**
- Consumes : Tasks 1 à 4 ; `candidates_sidecar(genealogy, index)`.
- Produces :
  - `archive_name(source_name: Optional[str], day: date) -> str` dans `table_writers.py` : `prosopo-<stem>-<AAAA-MM-JJ>.zip`, `stem` = `Path(source_name).stem` dont chaque caractère ni alphanumérique (`str.isalnum`) ni `-`/`_` devient `_`, `base` si vide ou `None`
  - `build_zip(tables: Sequence[Table], companion: Dict[str, Any], base: str, generated_at: datetime) -> bytes` dans `table_writers.py`
  - `build_export_bundle(genealogy: Genealogy, index: CandidateIndex, shared: SharedExperienceIndex, ignored_words: Sequence[str], source_name: Optional[str], now: datetime) -> Tuple[str, bytes]` dans `export_bundle.py` : (nom de l'archive, octets) ; tables = `build_base_tables` + `build_organization_tables` ; compagnon = `candidates_sidecar(...)` plus `"ignored_words": list(ignored_words)`

Contenu du zip, dans cet ordre, `ZIP_DEFLATED` : `LISEZMOI.txt`, `dictionnaire.csv`, `base.org.json` (`indent=2`, `ensure_ascii=False`), `base.sqlite`, `base.json`, puis `csv/<table>.csv` pour chaque table dans l'ordre des tables.

`LISEZMOI.txt` (UTF-8, texte fixe ; `{base}` et `{date}` substitués) :

```
Export prosopo-gw — base « {base} », {date}

Ce dossier contient des données personnelles issues de votre base généalogique.
Ne le publiez pas et ne le versionnez pas.

base.org.json      Mon travail : organisations retenues, liens et mots ignorés.
base.sqlite        Toutes les tables, pour SQL, pandas ou DB Browser for SQLite.
base.json          Toutes les tables, pour un script, Streamlit ou un LLM.
csv/               Une table par fichier, pour un tableur (UTF-8, séparateur « ; »).
dictionnaire.csv   Description de chaque colonne de chaque table.

Les identifiants (personne_id, famille_id, evenement_id…) relient les tables entre elles.
Ils sont stables pour un même fichier .gw, pas d'une version de la base à l'autre.
```

- [ ] **Step 1: Write the failing tests**

```python
def test_zip_file_list(): # liste exacte et ordonnée des fichiers (10 CSV)
def test_archive_name_sanitized(): # "ma base été.gw", date(2026, 11, 6) → "prosopo-ma_base_été-2026-11-06.zip" ; None → "prosopo-base-2026-11-06.zip"
def test_companion_has_ignored_words(): # base.org.json : "version", "organizations", "links", "ignored_words"
def test_readme_mentions_base_and_date():
def test_csv_in_zip_match_tables(): # chaque csv/<t>.csv == table_to_csv(t)
def test_empty_genealogy_bundle(): # Genealogy() vide : 10 CSV d'en-tête seul, SQLite ouvrable aux tables vides
```

- [ ] **Step 2: Run** `COLUMNS=200 uv run python -m pytest tests/api/test_export_bundle.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** toute la suite, mypy, ruff — Expected: PASS, 0 erreur ; puis, en lecture seule et hors dépôt, un essai sur la base réelle locale qui ne rapporte que des comptes (nombre de lignes par table, taille du zip), jamais de contenu.
- [ ] **Step 5: Commit** `feat(exports): bundle tables, dictionary and companion into one zip`

## Décisions prises dans ce plan

- Tables d'organisations construites côté `api/services/` : elles dépendent de l'index des candidates, et `formats/` reste sans dépendance vers l'API (écart à § 5.3, qui place toutes les tables dans `formats/tables.py`).
- `organisations` ne reprend pas les colonnes-listes `sources`, `lieux`, `roles` de l'actuel CSV ; `experiences_proches` garde `lieux` et `raison` en texte, comme aujourd'hui.
- `liens` gagne `annee`, `type_evenement_libelle`, `evenement_id`, `temoin`.
- `sexe` : `M`, `F` ou vide.
- Identifiant de source : hachage de cible, identifiant de cible et objet (unique après dédoublonnage).
- `Event.reason` n'est pas exporté (non demandé par la conception).
