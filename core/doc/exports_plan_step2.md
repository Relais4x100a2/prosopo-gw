# Exports, étape 2 : pistes tirées des notes — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ajouter à l'archive la table `pistes` : un extrait par passage de note qui évoque une organisation, rattaché à sa personne, son événement ou sa famille par les identifiants stables de l'étape 1.

**Architecture:** la détection travaille sur un texte seul, sans généalogie (`core/note_leads.py`), ce qui la rend testable et réutilisable par Streamlit. La table (`formats/leads_table.py`) parcourt les notes de la `Genealogy` et reçoit en paramètres les événements déjà rattachés à une organisation et les mots ignorés. `formats/` n'importe toujours rien de `api/`. `build_organization_tables` insère `pistes` entre `reste_a_classer` et `experiences_proches`, comme le veut l'ordre du § 4.1 ; l'archive passe donc à 11 CSV.

**Tech Stack:** Python ≥ 3.8 (paquet `core`), bibliothèque standard (`re`, `hashlib`, `unicodedata`), pytest.

**Spec:** `core/doc/exports_design.md`, § 4.1, 4.2, 6 et 10 (puce « pistes »). Hors étape : route, bouton et ligne de résumé (§ 5.3 dernière puce, § 7, étape 3) ; pistes de `nature = source` (§ 9).

## Global Constraints

- Aucune donnée réelle : fixtures synthétiques uniquement (`DUPONT Jean`, `MARTIN Marie`, `Banque Fictive`…), y compris dans les messages de commit. L'essai sur la base réelle locale ne rapporte que des comptes.
- Aucune dépendance ajoutée ; `formats/` et `core/` n'importent rien de `geneweb_py.api`.
- Vocabulaire réutilisé, jamais recopié : `ESTABLISHMENT_WORDS`, `LEGAL_FORMS`, `COMPANY_NAME_TRIGGERS`, `_fold` de `core/event_to_organization.py`.
- mypy 0 erreur (`uv run --package geneweb-py mypy core/src/geneweb_py` depuis la racine) ; ruff `uv run ruff check src tests --ignore E501` et `uv run ruff format src tests` depuis `core/`.
- Tests : `COLUMNS=200 uv run python -m pytest -q` depuis `core/` ; couverture ≥ 80 %.
- Commits `type(scope): message` en anglais, terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` ; `git add` par chemins explicites.

## Décisions à valider (le § 6 ne les tranche pas)

1. **Formes juridiques sensibles à la casse.** `SA`, `SNC`, `SARL`, `SAS`, `Et.` ne se déclenchent qu'écrites ainsi, comme dans `_establishment_in`. Les mots d'établissement, eux, se comparent sans casse ni accents (§ 6.2). Sans cette exception, « sa » et « et » transformeraient presque chaque note en piste.
2. **Note de Profession exploitée.** La note d'un événement Profession n'est pas reprise si l'événement est rattaché à une organisation (`index.matched`) et que `EventToOrganizationMapper().propose_from_occupation(note, ville)` y trouve un établissement (proposition avec `trigger`). Cas limite accepté : le complément de lieu nommait déjà l'organisation, et la note la répète ; la note n'est alors pas reprise non plus.
3. **Borne de 600 caractères.** Deux fenêtres ne fusionnent que si le résultat tient en 600 caractères. Sinon, la seconde ouvre une nouvelle piste : pas de texte coupé au milieu.
4. **Une piste par note.** Chaque élément de `Person.notes`, `Family.comments` ou `Event.notes` est lu séparément, et son rang entre dans `piste_id`.
5. **`type_devine`** reprend le code de `organisations.type` (`company`, `school`, `military`…). Il vient du premier déclencheur de l'extrait. Une forme juridique donne `company`. « Compagnie » suivie d'un nombre donne `military`.

## Review Focus

1. Note où la seule occurrence de « compagnie » est « en compagnie de » ou « en compagnie d' », en capitales ou non : aucune piste. → Task 1, `test_en_compagnie_de_ignored`.
2. Note réduite à une URL, ou dont le seul déclencheur est dans une URL (`https://usine.example/banque`) : aucune piste, et l'URL n'apparaît dans aucun extrait. → Task 1, `test_urls_removed`.
3. Très longue note à déclencheurs nombreux : aucun extrait ne dépasse 600 caractères, et chaque déclencheur figure dans un extrait. → Task 1, `test_extract_bounds`.
4. Famille sans mari, ou sans aucun conjoint connu : la piste se rattache à la femme, sinon `personne_id` reste vide. Pas d'exception. → Task 2, `test_family_note_owner`.
5. Tout `personne_id`, `evenement_id` et `famille_id` de `pistes` existe dans sa table. → Task 3, `test_lead_ids_resolve`.

---

### Task 1: Détection dans un texte de note

**Files:**
- Create: `src/geneweb_py/core/note_leads.py`
- Test: `tests/unit/test_note_leads.py`

**Interfaces:**
- Consumes: `ESTABLISHMENT_WORDS`, `LEGAL_FORMS`, `COMPANY_NAME_TRIGGERS`, `_fold` (`core/event_to_organization.py`).
- Produces:
  - `NoteLead` (dataclass figée) : `start: int`, `end: int`, `words: Tuple[str, ...]` (déclencheurs repliés, sans doublon, dans l'ordre), `guessed_type: str`, `strong: bool`, `excerpt: str`.
  - `find_note_leads(text: str, ignored_words: Iterable[str] = ()) -> List[NoteLead]`, en ordre de position.
  - `EXCERPT_RADIUS = 150`, `EXCERPT_MAX = 600`.

**Algorithme** (le seul point que les tests ne fixent pas entièrement) :
1. Remplacer chaque URL (`https?://\S+`, `www\.\S+`) par autant d'espaces, pour garder les positions.
2. Découper en mots avec leurs positions (`[\w'’.]+`, le point final seulement pour `Et.`). Un mot déclenche s'il est dans `LEGAL_FORMS` tel qu'écrit, ou si sa forme repliée (`_fold`, sans le point final) est une clé de `ESTABLISHMENT_WORDS`. Il est écarté s'il figure dans les mots ignorés repliés, ou s'il s'agit de « compagnie » précédé de « en » et suivi de « de » ou « d' ».
3. Piste forte : un déclencheur de `COMPANY_NAME_TRIGGERS` à initiale capitale, suivi d'un mot à initiale capitale (au plus un mot de liaison entre les deux : `de`, `du`, `des`, `d'`, `la`, `le`, `les`, `l'`, `et`) ; ou un mot à initiale capitale suivi d'une forme de `LEGAL_FORMS`.
4. Fenêtre `[début − 150, fin + 150]`, élargie aux limites de mots. Les fenêtres qui se recouvrent fusionnent tant que le résultat ne dépasse pas 600 caractères (décision 3). Extrait : espaces réduites, `strip()`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_note_leads.py`:
  - `test_establishment_word_found`: `find_note_leads("Il entre à la banque du village en 1890.")` gives one lead, with `words == ("banque",)`, `guessed_type == "company"`, `strong is False`, and `"banque du village"` in its excerpt.
  - `test_accented_capitals`: `"Directeur des ÉTABLISSEMENTS Durand"` gives `words == ("etablissements",)` and `strong is True`.
  - `test_strong_company_name`: `"Associé de la Société des Forges Fictives."` is strong; `"une société de pêche"` is not.
  - `test_legal_form_case_sensitive`: `"Fonde DUPONT SNC avec son frère"` is strong with `words == ("snc",)`; `"sa maison et sa grange"` gives `[]`.
  - `test_en_compagnie_de_ignored`: `"Parti en compagnie de son frère"` and `"EN COMPAGNIE D'un ami"` give `[]`; `"Entre à la Compagnie des Mines"` gives one lead.
  - `test_compagnie_number_is_military`: `"Sert dans la Compagnie 3 du régiment"` gives `guessed_type == "military"`.
  - `test_ignored_word`: `find_note_leads("Travaille à l'usine", ignored_words=["Usine"]) == []`.
  - `test_urls_removed`: `"https://usine.example/banque"` gives `[]`; for `"Voir www.banque.example ; employé à l'usine"`, one lead whose excerpt contains no `"www"`.
  - `test_empty_note`: `""`, `"   "` and `"Né à Villefictive."` each give `[]`.
  - `test_windows_merged`: two triggers 100 characters apart give one lead with both words.
  - `test_extract_bounds`: for `" ".join((["usine"] + ["mot"] * 400) * 3)`, every excerpt is ≤ 600 characters, no lead has a trigger outside its excerpt, and the excerpts together cover the 3 triggers.

- [ ] **Step 2: Run them to verify they fail**
  Run: `COLUMNS=200 uv run python -m pytest tests/unit/test_note_leads.py -q`
  Expected: collection error, `ModuleNotFoundError: geneweb_py.core.note_leads`.

- [ ] **Step 3: Implement `find_note_leads`** in `src/geneweb_py/core/note_leads.py`, following the algorithm above.

- [ ] **Step 4: Run them to verify they pass**, then run the full suite, ruff and mypy.
  Expected: 11 passed ; suite verte ; ruff et mypy sans erreur.

- [ ] **Step 5: Commit**
  `git add src/geneweb_py/core/note_leads.py tests/unit/test_note_leads.py`
  `git commit -m "feat(exports): detect organization leads in note text"`

### Task 2: Table `pistes`

**Files:**
- Create: `src/geneweb_py/formats/leads_table.py`
- Test: `tests/formats/test_leads_table.py`

**Interfaces:**
- Consumes: `find_note_leads` (Task 1) ; `Column`, `Table`, `TableSpec`, `Row`, `family_event_ref` (`formats/tables.py`) ; `event_ref`, `EventToOrganizationMapper`, `EventType` (core).
- Produces:
  - `PISTES: TableSpec`, avec les colonnes du § 6.3, dans cet ordre : `piste_id` (clé primaire), `personne_id`, `evenement_id`, `famille_id`, `nature`, `origine`, `mots`, `type_devine`, `forte` (`bool`), `extrait`. Chaque colonne porte une description en français.
  - `build_leads_table(genealogy: Genealogy, matched: AbstractSet[Tuple[str, int]], ignored_words: Iterable[str]) -> Table`.

Règles :
- Ordre des lignes : personnes (notes de la personne, puis de ses événements), puis familles (commentaires, puis événements familiaux), chacune dans l'ordre de `Genealogy`.
- `nature = "organisation"`. `mots` contient les déclencheurs joints par une espace.
- Rattachement d'une famille ou d'un événement familial : `personne_id` = mari s'il existe dans `genealogy.persons`, sinon femme, sinon `None`.
- Identifiant : `piste_id = "p-" + sha1(f"{origine}|{cible_id}|{rang_note}|{start}")[:12]`, où `cible_id` est l'identifiant de la personne, de l'événement ou de la famille.
- Décision 2 pour les notes de Profession. La ville passée à `propose_from_occupation` est `event.place_parts.city`.

- [ ] **Step 1: Write the failing tests** in `tests/formats/test_leads_table.py`, on an inline GW fixture. It has a person note mentioning a bank, a pevt event note mentioning a factory, a `comm` family note mentioning a company, and a family event note.
  - `test_columns`: `PISTES.column_names` equals the § 6.3 list, and `PISTES.primary_key == "piste_id"`.
  - `test_each_origin`: the set of `origine` values is `{"personne", "evenement", "famille", "evenement_familial"}`. Each row's ids match its origin: `evenement_id` starts with `pevt:` or `fevt:` only for event origins, and `famille_id` is set only for family origins.
  - `test_family_note_owner`: in a family without a husband, the row's `personne_id` is the wife; in a family with no spouse at all, it is `None`.
  - `test_occupation_note_used_by_org_skipped`: `#occu` event with note `"Employé à la Banque Fictive"`. With `matched = {(pid, 0)}` the table has no row for that event. With `matched = set()` it has one.
  - `test_ignored_words_passed`: `ignored_words=["banque"]` removes the bank lead.
  - `test_ids_stable_and_unique`: two calls give the same `piste_id` list, with no duplicates.
  - `test_empty_genealogy`: `build_leads_table(Genealogy(), set(), [])` has no rows.

- [ ] **Step 2: Run them to verify they fail**
  Run: `COLUMNS=200 uv run python -m pytest tests/formats/test_leads_table.py -q`
  Expected: `ModuleNotFoundError: geneweb_py.formats.leads_table`.

- [ ] **Step 3: Implement `PISTES` and `build_leads_table`** in `src/geneweb_py/formats/leads_table.py`.

- [ ] **Step 4: Run them to verify they pass**, then run the full suite, ruff and mypy.
  Expected: 7 passed ; suite verte.

- [ ] **Step 5: Commit**
  `git add src/geneweb_py/formats/leads_table.py tests/formats/test_leads_table.py`
  `git commit -m "feat(exports): build the leads table from person, event and family notes"`

### Task 3: Intégration dans l'archive

**Files:**
- Modify: `src/geneweb_py/api/services/organization_tables.py` (`build_organization_tables`)
- Modify: `tests/api/test_organization_tables.py`, `tests/api/test_export_bundle.py` (ordre des tables)
- Test: `tests/api/test_export_bundle.py`

**Interfaces:**
- Consumes: `PISTES`, `build_leads_table` (Task 2) ; `CandidateIndex.matched`.
- Produces: `build_organization_tables` renvoie 5 tables : `organisations`, `liens`, `reste_a_classer`, `pistes`, `experiences_proches`. L'archive contient 11 CSV.

- [ ] **Step 1: Write the failing tests**
  - In `test_organization_tables.py`, update the expected table order to include `pistes` in 4th position.
  - In `test_export_bundle.py`, add `"pistes"` to `TABLE_NAMES` between `reste_a_classer` and `experiences_proches`. Add a note mentioning a factory to the fixture.
  - Add `test_lead_ids_resolve` to `test_export_bundle.py`. It opens `base.sqlite` from the zip and checks that every non-empty `personne_id`, `evenement_id` and `famille_id` in `pistes` exists in `personnes`, `evenements` and `familles` (`LEFT JOIN … WHERE … IS NULL` returns 0 rows), and that `pistes` holds at least one row.
  - Add `test_dictionary_lists_pistes`: `dictionnaire.csv` in the zip has the 10 `pistes` columns.

- [ ] **Step 2: Run them to verify they fail**
  Run: `COLUMNS=200 uv run python -m pytest tests/api/test_organization_tables.py tests/api/test_export_bundle.py -q`
  Expected: failures on the table order and file list (`pistes` missing).

- [ ] **Step 3: Insert the `pistes` table** in `build_organization_tables`. Call `build_leads_table(genealogy, index.matched, ignored_words)`.

- [ ] **Step 4: Run them to verify they pass**, then run the full suite, ruff and mypy.
  Then a read-only run on the local real base, from a scratchpad script. Report only: number of leads, number of strong leads, count per `origine`, longest excerpt length (≤ 600), zip size and duration.
  Expected: suite verte ; aucun extrait > 600.

- [ ] **Step 5: Commit**
  `git add src/geneweb_py/api/services/organization_tables.py tests/api/test_organization_tables.py tests/api/test_export_bundle.py`
  `git commit -m "feat(exports): add the leads table to the export bundle"`
