# Organisations probables et expériences proches : plan de mise en œuvre

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Écarter d'office l'état civil, ne garder que les organisations à signal fort, et calculer, afficher et exporter en CSV des « expériences proches » sans aucune persistance.

**Architecture:** Les tables de mots (état civil, voies) et la détection d'adresse rejoignent les autres tables de `core/event_to_organization.py`. Un nouveau module pur `core/shared_experiences.py` calcule les expériences proches à partir d'une `Genealogy` et d'un ensemble d'événements exclus. L'API les met en cache par session, à côté de l'index des candidates, avec la même invalidation ; la webapp statique les affiche dans une seconde section de l'onglet Organisations.

**Tech Stack:** Python ≥ 3.11 (workspace), dataclasses, FastAPI + Pydantic, JS/HTML/CSS statiques sans bibliothèque, pytest, ruff, mypy strict.

**Spec:** `core/doc/shared_experiences_design.md` (commit 06acd78). Les « § » ci-dessous renvoient à cette spec.

## Global Constraints

- Dépôt **public** : fixtures synthétiques uniquement (noms fictifs `DUPONT Jean`, lieux fictifs ou génériques) ; aucun nom, lieu, date ou extrait de la base réelle dans le code, les tests, les docs ou les commits.
- Commandes depuis `core/` : `COLUMNS=250 uv run python -m pytest -q`, `uv run ruff check src tests --ignore E501`, `uv run ruff format src tests` ; depuis la racine : `uv run --package geneweb-py mypy core/src/geneweb_py` (0 erreur), `node --check core/src/geneweb_py/api/static/app.js`.
- Couverture `core` ≥ 80 % ; annotations de types partout ; pas de `# type: ignore` sans justification.
- Code, identifiants, commits en anglais (`type(scope): message`, un sujet par commit, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`) ; textes visibles et docs en français.
- `git add` avec chemins explicites, puis `git diff --cached --name-only` ; ni `git add -A`, ni push.
- Repliement des mots : `_fold` / `_words` existants de `core/event_to_organization.py` (sans casse ni accents, séparateurs `_ - espace '`).
- Vocabulaire : « personnes » pour une expérience proche, jamais « membres ».
- CSP `default-src 'self'` : aucune bibliothèque externe dans la webapp ; tout texte inséré passe par `escHtml`.

## Review Focus

1. Un tag générique très fréquent (des centaines d'événements d'un même thème, une même année) : le calcul doit rester rapide (comparaisons limitées à la tranche, fréquences précalculées). Test de charge en Task 3.
2. Un tag sans lettre (`#1914`, `#_`) ou dont la clé de thème est vide après retrait des chiffres : l'événement est ignoré, pas d'exception. Test en Task 3.
3. Une note faite uniquement de mots outils, de la ville ou de mots de moins de 4 lettres : ensemble de mots vide, aucun lien par mot, aucune exception. Test en Task 3.
4. Une session chargée avec un ancien `.org.json` (organisations présentes, pas d'inférence) contenant des organisations faibles nommées d'après un tag : elles sont écartées de la même façon et leurs événements nourrissent les expériences proches. Test en Task 4.
5. Un navigateur qui restaure d'anciens mots ignorés (`recensement`, `domicile`) depuis le `localStorage` : le PUT reste accepté, et un événement à la fois d'état civil et ignoré est compté **une seule fois**, comme état civil. Test en Task 2.

---

### Task 1: Tables de mots, adresses et signal fort dans le moteur

**Files:**
- Modify: `core/src/geneweb_py/core/event_to_organization.py` (tables près de `RELATION_WORDS` ~l.228 ; branche 2 de `propose` ~l.402-445)
- Test: `core/tests/unit/test_probable_organizations.py` (nouveau) ; mettre à jour `core/tests/unit/test_event_to_organization.py` là où il attend 0,5 pour un tag contenant un mot d'établissement

**Interfaces:**
- Produces:
  - `CIVIL_STATUS_WORDS: FrozenSet[str]` = exactement les 15 mots du § 3.1 (`naissance`, `bapteme`, `mariage`, `divorce`, `separation`, `fiancailles`, `bans`, `reconnaissance`, `legitimation`, `adoption`, `deces`, `inhumation`, `sepulture`, `recensement`, `domicile`), sans `contrat` ni `publication`.
  - `is_civil_status(tag: Optional[str]) -> bool` : vrai si un mot de `_words(tag)` est dans `CIVIL_STATUS_WORDS`.
  - `STREET_WORDS: FrozenSet[str]` = les 13 mots du § 3.2 (`rue`, `passage`, `avenue`, `boulevard`, `place`, `impasse`, `quai`, `chemin`, `allee`, `cours`, `square`, `villa`, `cite`).
  - `MONTH_WORDS: FrozenSet[str]` = les 12 mois repliés (`janvier` … `decembre`, `fevrier`, `aout`).
  - `address_in(text: Optional[str]) -> bool` : règles 1 à 4 du § 3.2.
  - Proposition « adresse » : `named_from="address"`, `type=OrganizationType.OTHER`, `confidence=_CONF_OCCUPATION_TEXT` (0,7), `name` = le texte qui porte l'adresse (`tag_name` lisible, ou le complément), `role` de la règle de préfixe s'il y en a une.

- [ ] **Step 1: Écrire les tests qui échouent** dans `test_probable_organizations.py` :

```python
@pytest.mark.parametrize("tag, expected", [
    ("Mariage", True), ("Reconnaissance_enfant", True), ("Contrat_de_mariage", True),
    ("Publication_des_bans", True), ("Deces", True), ("Décès", True),
    ("Contrat_Engagement", False), ("Publication_ouvrage", False), ("Deportation", False), (None, False),
])
def test_is_civil_status(tag, expected): assert is_civil_status(tag) is expected

@pytest.mark.parametrize("text, expected", [
    ("Passage_Fictif_7", True), ("7_passage_Fictif", True), ("12_bis_rue_Haute", True),
    ("passage Fictif, 7", True), ("Rue_du_14_Juillet_3", True),
    ("Rue_du_14_Juillet", False), ("Avenue_du_8_Mai", False), ("Place_du_11_Novembre", False),
    ("8_Mai_avenue", False), ("Cercle_Fictif_7", False), ("Rue_Haute", False), ("Passage_12345", False),
])
def test_address_in(text, expected): assert address_in(text) is expected
```

Plus, via `EventToOrganizationMapper().propose(event, counts)` sur des `Event` « Autre » construits à la main :
- `test_address_tag_is_a_probable_organization` : tag `Passage_Fictif_7`, compte 2 → `named_from == "address"`, `confidence == 0.7`, `review_required is False`.
- `test_address_in_complement` : tag `Habitant`, lieu `[7_passage_Fictif]_-_Lille` → `named_from == "address"`, `name == "7 passage Fictif"` (forme lisible du complément, comme les autres noms issus du lieu).
- `test_establishment_tag_without_prefix_is_strong` : tag `Ecole_Fictive`, compte 2 → `confidence == 0.8`.
- `test_plain_tag_stays_weak` : tag `Cercle_Philatelique`, compte 2 → `confidence == 0.5`, `named_from == "tag"` (le moteur garde la proposition faible, § 3.2 ; c'est l'index qui l'écarte en Task 2).

- [ ] **Step 2: Lancer** `COLUMNS=250 uv run python -m pytest tests/unit/test_probable_organizations.py -q` → échec à l'import (`is_civil_status` absent).

- [ ] **Step 3: Implémenter** dans `event_to_organization.py` les tables, `is_civil_status`, `address_in`, puis l'ordre des branches de `propose` pour un événement « Autre » :
  1. complément avec mot d'établissement (inchangé, 0,8) ;
  2. tag avec préfixe de rôle (inchangé, 0,8) ;
  3. tag sans préfixe contenant un mot d'établissement, compte ≥ 2 → 0,8 (au lieu de 0,5) ;
  4. **nouveau** : adresse dans `tag_name`, sinon dans le complément → proposition « adresse » (sans condition de compte) ;
  5. tag faible et tag de relation (inchangés, 0,5) ;
  6. complément « à déterminer » (inchangé).

  `address_in` : texte replié, `_` et `,` remplacés par des espaces, découpé en mots ; numéro = mot de 1 à 4 chiffres, éventuellement suivi de `bis`/`ter`/`quater` ; il doit être le premier mot, ou le dernier (le dernier mot pouvant être `bis`/`ter`/`quater` précédé du nombre) ; refusé si le mot voisin (suivant pour un numéro en tête, précédent pour un numéro en fin) est dans `MONTH_WORDS`.

- [ ] **Step 4: Lancer** `COLUMNS=250 uv run python -m pytest tests/unit/test_probable_organizations.py tests/unit/test_event_to_organization.py -q` → tout passe (ajuster dans `test_event_to_organization.py` les seules attentes « tag avec mot d'établissement sans préfixe = 0,5 », en 0,8).

- [ ] **Step 5: Commit** `feat(core): civil-status words, address detection and stronger establishment tags`.

---

### Task 2: Index des candidates : état civil écarté, organisations faibles retirées

**Files:**
- Modify: `core/src/geneweb_py/api/services/organization_candidates.py`
- Modify: `core/src/geneweb_py/api/routers/organizations.py` (`/unmatched`, docstring des mots ignorés), `core/src/geneweb_py/api/models/organization.py` (`UnmatchedResponseSchema`, description des mots ignorés), `core/src/geneweb_py/api/services/organization_exports.py` (`NAMED_FROM_LABELS`)
- Test: `core/tests/api/test_probable_candidates.py` (nouveau) ; mettre à jour `core/tests/api/test_organization_followups.py` (défauts et comptes fondés sur « recensement »/« domicile »)

**Interfaces:**
- Consumes: `is_civil_status`, `named_from="address"` (Task 1).
- Produces:
  - `DEFAULT_IGNORED_WORDS: Tuple[str, ...] = ()`.
  - `CandidateIndex.civil_status_total: int = 0` (nouveau champ) et `CandidateIndex.matched: FrozenSet[Tuple[str, int]] = frozenset()` : références `(person_id, index)` des événements rattachés aux candidates **retenues**.
  - `is_weak_tag_organization(org: Organization) -> bool` : `org.metadata.get("named_from") == "tag" and (org.confidence or 0.0) < REVIEW_THRESHOLD`.
  - `GET /api/v1/organizations/unmatched` ajoute `"civil_status_total"`.
  - `NAMED_FROM_LABELS["address"] = "Adresse"`.

- [ ] **Step 1: Écrire les tests qui échouent.** Fixture `.gw` synthétique (personnes `DUPONT Jean`, `MARTIN Marie`, `DURAND Paul`) avec, pour au moins deux personnes : `#Mariage 1900 #p [Mairie]_-_Lille`, `#Reconnaissance_enfant 1901`, `#Recensement 1906 #p Lille`, `#Cercle_Philatelique 1900`, `#Passage_Fictif_7 1910`, `#Contrat_Engagement 1912`, `#educ 1880 #p [Ecole_Saint_Paul]_-_Lille`. Tests :
  - `test_civil_status_never_candidate_nor_unmatched` : aucun nom de candidate ne contient « Mairie », « Mariage », « Recensement » ; aucun tag d'état civil dans `unmatched_groups` ; `civil_status_total == 6` (2 mariages, 2 reconnaissances, 2 recensements — ajuster au nombre réel de la fixture).
  - `test_contrat_engagement_is_not_civil_status` : `Contrat_Engagement` figure dans le reste à classer.
  - `test_weak_tag_organization_is_dropped` : pas de candidate « Cercle Philatelique » ; ses événements ne sont pas dans `index.matched`.
  - `test_address_and_typed_candidates_kept` : candidates « Passage Fictif 7 » (`named_from == "address"`) et l'école (`typed_event`/`place`) présentes, leurs événements dans `index.matched`.
  - `test_default_ignored_words_empty` : `DEFAULT_IGNORED_WORDS == ()`.
  - `test_civil_and_ignored_counted_once` (Review Focus 5) : `build_candidate_index(g, ["recensement", "domicile"])` → `ignored_total == 0` pour les recensements, comptés dans `civil_status_total`.
  - `test_unmatched_endpoint_has_civil_status_total` (client avec `dependency_overrides`, comme `test_organization_followups.py`).

- [ ] **Step 2: Lancer** `COLUMNS=250 uv run python -m pytest tests/api/test_probable_candidates.py -q` → échec.

- [ ] **Step 3: Implémenter.** Un événement résolu « Autre » dont le tag `is_civil_status` est écarté avant le test des mots ignorés, dans `_build_candidates` (ses liens ne nourrissent aucune candidate) et dans `_build_unmatched` (compté dans `civil_status_total`, pas dans `ignored_total`). Dans `_build_candidates`, une organisation `is_weak_tag_organization` n'est pas retenue et ses références ne vont pas dans `matched`. `build_candidate_index` remplit `matched`. Mettre à jour les docstrings et la description Pydantic qui citent « recensement, domicile » comme défaut.

- [ ] **Step 4: Lancer** toute la suite `COLUMNS=250 uv run python -m pytest -q` ; réécrire dans `test_organization_followups.py` les tests qui supposaient les défauts (utiliser un mot neutre, par ex. `cercle`, pour éprouver les mots ignorés) → tout passe.

- [ ] **Step 5: Commit** `feat(api): exclude civil-status events and weak tag organizations from candidates`.

---

### Task 3: Module `core/shared_experiences.py`

**Files:**
- Create: `core/src/geneweb_py/core/shared_experiences.py`
- Test: `core/tests/unit/test_shared_experiences.py`

**Interfaces:**
- Consumes: `_fold`, `_words`, `is_civil_status`, `RELATION_WORDS` (Task 1) ; `place_city` (`core/place.py`) ; `Date.filter_years_for_range()`, `Date.prefix`, `DatePrefix`.
- Produces:

```python
RARE_WORD_MAX_NOTES = 5
MIN_NOTE_WORD_LEN = 4
STOPWORDS: FrozenSet[str]            # courte : articles, prépositions, pronoms, « date », « annee », « mois », « jour »…

@dataclass(frozen=True)
class Theme:
    key: str        # "deportation", "internement", "resistance", "voyage", "relation", ou tag replié
    label: str      # "Déportation", "Internement", "Résistance", "Voyage", "Amitié et relations", ou tag lisible
    window: int     # 0, 0, 0, 1, 3, 1
    prefix: Optional[str]   # "deport", "intern", "resist", "voyag", None

SHARED_EXPERIENCE_THEMES: Tuple[Theme, ...]   # les quatre thèmes à préfixe ; « relation » est reconnu par RELATION_WORDS

@dataclass(frozen=True)
class SharedReason:
    kind: str                     # "same_place" | "rare_word"
    place: Optional[str] = None   # ville lisible pour same_place
    words: Tuple[str, ...] = ()   # au plus 3, triés, pour rare_word

@dataclass
class SharedExperienceEvent:
    person_id: str
    event_index: int
    event_type_raw: str
    year_start: int
    year_end: int
    place: Optional[str]          # lieu brut
    city: Optional[str]           # place_city(place)

@dataclass
class SharedExperience:
    id: str                        # "exp-" + 10 premiers caractères hexadécimaux du sha1 de "theme.key|ref1|ref2…" (refs triées "person_id:index")
    theme: str
    label: str
    year_min: int
    year_max: int
    places: List[str]              # villes distinctes triées
    reasons: List[SharedReason]    # distinctes, triées (kind, place, words)
    events: List[SharedExperienceEvent]   # dans l'ordre de parcours
    person_count: int
    event_count: int

@dataclass
class SharedExperienceIndex:
    items: List[SharedExperience]
    undated_total: int

def theme_of(tag: str) -> Optional[Theme]
def event_period(date: Optional[Date]) -> Optional[Tuple[int, int]]
def period_gap(a: Tuple[int, int], b: Tuple[int, int]) -> int
def singularize(word: str) -> str
def note_words(text: str) -> FrozenSet[str]
def find_shared_experiences(
    genealogy: Genealogy,
    exclude: AbstractSet[Tuple[str, int]] = frozenset(),
    ignored_words: AbstractSet[str] = frozenset(),
) -> SharedExperienceIndex
```

Règles exactes (spec § 4.1-4.3) :
- `theme_of` : `None` si le tag est d'état civil ou si sa clé est vide ; sinon le premier thème dont un mot de `_words(tag)` commence par `prefix` ; sinon « relation » si un mot est dans `RELATION_WORDS` ; sinon `Theme(key=<mots alphabétiques du tag replié, joints par "_", chiffres retirés>, label=<tag, "_" → " ">, window=1, prefix=None)`.
- `event_period` : `None` si date absente, inconnue, textuelle, ou préfixe `BEFORE`/`AFTER` ; sinon `(min, max)` de `filter_years_for_range()` (`None` si vide).
- `period_gap(a, b) = max(0, max(a[0], b[0]) - min(a[1], b[1]))`.
- `singularize` : mot de 5 lettres ou plus finissant par `s` ou `x` → sans cette lettre ; sinon inchangé.
- `note_words` : mots alphabétiques de `_fold(text)` d'au moins 4 lettres, hors `STOPWORDS`, passés par `singularize`.
- Mots d'un événement = `note_words(" ".join(event.notes))` moins `note_words(city)`, moins `note_words(tag)`, moins les mots commençant par `theme.prefix`.
- Fréquences : un seul `Counter` sur les ensembles de mots (avant retrait ville/thème) de **toutes** les notes d'événements personnels de la base, calculé une fois ; rare ⇔ `df[w] <= RARE_WORD_MAX_NOTES`.
- Entrée : événements personnels « Autre » non civils, non ignorés (mot entier de `ignored_words`), dont `(person_id, index)` n'est pas dans `exclude`, avec un thème. Sans période → `undated_total += 1`, jamais lié.
- Même lieu : `_fold(city).strip()` non vide, différent de `"?"`, égal des deux côtés. Les deux raisons sont enregistrées quand les deux s'appliquent.
- Algorithme déterministe du § 4.1 : tri `(start, end, person_id, event_index)`, tranches d'étendue `E = max(1, 2 * window)` (la tranche reçoit tous les événements non placés dont la fin est `≤ D + E`), union-find dans la tranche en parcourant les paires dans l'ordre, composante retenue si ≥ 2 personnes distinctes, tri final `(theme.key, year_min, id)`.

- [ ] **Step 1: Écrire les tests qui échouent** (fixtures `.gw` synthétiques parsées avec `GeneWebParser().parse_string`, notes en `note` sous l'événement, comme dans les fixtures existantes) :
  - unitaires : `theme_of("Deportation")`, `theme_of("Membre_Resistance").key == "resistance"`, `theme_of("Amitie_avec_X").window == 3`, `theme_of("Voyage_Italie").window == 1`, `theme_of("Mariage") is None`, `theme_of("1914") is None`, `theme_of("Cercle_2").key == "cercle"` ;
  - `event_period` : `1943` → `(1943, 1943)` ; `~1943` et `?1943` → `(1943, 1943)` ; `1942..1944` → `(1942, 1944)` ; `1940|1946` → `(1940, 1946)` ; `<1940`, `>1940`, `0(vers la guerre)`, `None` → `None` ;
  - `period_gap((1942, 1944), (1943, 1943)) == 0`, `period_gap((1940, 1940), (1943, 1943)) == 3` ;
  - `singularize("camps") == "camp"`, `singularize("convois") == "convoi"`, `singularize("gaz") == "gaz"`, `singularize("bus") == "bus"` (moins de 5 lettres) ;
  - intégration `find_shared_experiences` : même année + même ville → une expérience, raison `same_place` ; années trop éloignées → aucune ; deux événements sans ville et sans note → aucune ; ville `?` des deux côtés → aucune ; villes différentes + mot rare commun (« Fictivecamp » dans les deux notes) → une expérience, raison `rare_word` avec ce mot ; mot commun présent dans 6 notes de la fixture → aucune ; « camp » et « camps » rares → liés ; la ville de l'événement citée dans les deux notes ne lie pas, un autre lieu cité dans les deux notes lie ; deux événements de la même personne → aucune ; `exclude` retire un événement ; mot ignoré retire un événement ; `undated_total` compte `<1940` et une date textuelle ;
  - `test_chain_split_window_0` et `test_chain_split_window_1` : l'exemple A–B–C–D du § 4.1 (thème Déportation pour la fenêtre 0, Voyage pour la fenêtre 1) ; `test_order_independent` : même résultat (ids et événements) en inversant l'ordre des blocs dans le fichier ;
  - Review Focus 1 : `test_large_theme_is_fast` : 1 500 événements `#Voyage` la même année dans 30 villes, `find_shared_experiences` en moins de 2 s ;
  - Review Focus 2 : tags `#1914` et `#_` → ignorés sans exception ;
  - Review Focus 3 : notes ne contenant que des mots outils, la ville et des mots courts → aucun lien par mot, pas d'exception.

- [ ] **Step 2: Lancer** `COLUMNS=250 uv run python -m pytest tests/unit/test_shared_experiences.py -q` → échec à l'import.

- [ ] **Step 3: Implémenter** le module selon les interfaces et règles ci-dessus (docstrings en français, comme le reste de `core/`).

- [ ] **Step 4: Lancer** le fichier de tests puis `uv run --package geneweb-py mypy core/src/geneweb_py` (depuis la racine) → tout passe, 0 erreur.

- [ ] **Step 5: Commit** `feat(core): shared experiences grouping`.

---

### Task 4: Service, API et export CSV

**Files:**
- Modify: `core/src/geneweb_py/api/services/genealogy_service.py` (cache, `_invalidate_caches`, `set_ignored_words`)
- Modify: `core/src/geneweb_py/api/routers/organizations.py`, `core/src/geneweb_py/api/models/organization.py`
- Modify: `core/src/geneweb_py/api/services/organization_exports.py`, `core/src/geneweb_py/api/routers/genealogy.py`
- Test: `core/tests/api/test_shared_experiences_api.py`

**Interfaces:**
- Consumes: `find_shared_experiences`, `SharedExperienceIndex` (Task 3) ; `CandidateIndex.matched`, `civil_status_total` (Task 2) ; `person_display_name`.
- Produces:
  - `GenealogyService.get_shared_experiences() -> SharedExperienceIndex` : calcule d'abord `get_candidate_index()`, puis `find_shared_experiences(self.genealogy, index.matched, set(self._ignored_words))` ; cache `self._shared_experiences`, remis à `None` dans `_invalidate_caches` et quand les mots ignorés changent.
  - `SHARED_EXPERIENCES_CAP = 500`.
  - `GET /api/v1/organizations/shared-experiences` → `SharedExperiencesResponseSchema` : `items: List[SharedExperienceSchema]`, `total`, `civil_status_total`, `undated_total`, `truncated: bool`. `SharedExperienceSchema` : `id`, `theme`, `label`, `year_min`, `year_max`, `places`, `reasons` (`kind`, `place`, `words`), `person_count`, `event_count`, `persons` (liste de `person_id`, `person_name`, `event_type_raw`, `label` = tag lisible, `year_start`, `year_end`, `place`).
  - `shared_experiences_csv(genealogy: Genealogy, index: SharedExperienceIndex) -> str` dans `organization_exports.py`, mêmes helpers (`_render`, BOM, `;`).
  - `GET /api/v1/genealogy/export/shared-experiences-csv`, fichier `experiences_proches.csv`, `@limiter.limit("40/minute")`, déclarée **avant** `/export/{format}`.

CSV (§ 5) : en-tête exact `experience;theme;periode;lieux;raison;personne;evenement;annee;lieu` ; une ligne par événement ; `experience` = id ; `periode` = `1943` ou `1942-1944` (sur `year_min`/`year_max`) ; `lieux` = villes jointes par `, ` ; `raison` = raisons jointes par ` ; `, chacune « même lieu » ou « mot commun : x, y » ; `annee` = `year_start` ou `year_start-year_end` ; lignes dans l'ordre des expériences, puis par nom de personne replié, puis année.

- [ ] **Step 1: Écrire les tests qui échouent** (fixture synthétique : deux déportations même année même ville, un `#Cercle_Philatelique` partagé, un mariage, un événement `<1940`) :
  - `test_shared_experiences_endpoint` : `total == len(items)`, la déportation présente avec `person_count == 2`, `reasons[0].kind == "same_place"`, `civil_status_total >= 1`, `undated_total == 1`, `truncated is False` ;
  - `test_weak_tag_flows_to_shared_experiences` : `Cercle Philatelique` absent des candidates, présent comme expérience si même ville et même année ;
  - `test_shared_experiences_csv` : BOM, séparateur `;`, en-tête exact, lignes triées, `Content-Disposition` contenant `experiences_proches.csv` ;
  - `test_cache_invalidated_after_write_real_session` : vraie session (`create_app` + `POST /api/v1/sessions`), lecture de l'endpoint, modification d'un événement via l'API d'écriture existante (retrait du lieu d'une déportation), relecture → l'expérience a disparu ;
  - `test_ignored_word_change_recomputes` : PUT des mots ignorés avec `deportation` → l'expérience disparaît ;
  - Review Focus 4 : `test_sidecar_weak_orgs_filtered` : `Genealogy` avec une organisation chargée (`named_from="tag"`, `confidence=0.5`, liens vers les deux déportations) → absente des candidates, expérience proche présente.

- [ ] **Step 2: Lancer** `COLUMNS=250 uv run python -m pytest tests/api/test_shared_experiences_api.py -q` → échec.

- [ ] **Step 3: Implémenter** service, schémas, routes et CSV selon les interfaces.

- [ ] **Step 4: Lancer** toute la suite, ruff et mypy → tout passe.

- [ ] **Step 5: Commit** `feat(api): shared experiences endpoint and CSV export`.

---

### Task 5: Webapp — onglet en deux sections, export, Stats

**Files:**
- Modify: `core/src/geneweb_py/api/static/index.html` (panneau `#panel-organizations` l.165-220, bloc `export-orgs` l.234-241)
- Modify: `core/src/geneweb_py/api/static/app.js` (zone organisations l.1700-1980, carte Stats l.2082-2100, exports, `NAMED_FROM_LABELS` l.1703)
- Modify: `core/src/geneweb_py/api/static/style.css`
- Test: `core/tests/api/test_static_frontend.py`

**Interfaces:**
- Consumes: `GET /api/v1/organizations/shared-experiences`, `GET /api/v1/organizations/unmatched` (`civil_status_total`), `GET /api/v1/genealogy/export/shared-experiences-csv`.
- Produces (identifiants DOM, testés) : `orgs-section`, `orgs-count`, `exp-section`, `exp-count`, `exp-list`, `orgs-settings` (`<details>` replié contenant la ligne des mots ignorés, `orgs-excluded-info` et `orgs-unmatched`), `btn-export-exp-csv`, option `address` dans `#orgs-source`.

Textes exacts (§ 6) :
- intro : « Organisations déduites de vos événements, et personnes ayant vécu une expérience proche. Ce sont des propositions : rien n'est modifié dans votre fichier. »
- titres : « Organisations (N) », « Expériences proches (N) » ; phrase de section : « Personnes ayant vécu un événement de même nature, à la même période, au même lieu ou avec un indice commun dans leurs notes. Ce n'est pas une appartenance à une organisation. »
- carte : titre « {label} · {villes jointes par ", " ou "lieu inconnu"} · {1943 | 1942-1944} », « N personnes », pastilles « Même lieu » / « Mot commun : x, y » ; `<details>` dépliant la liste (nom cliquable vers la fiche via le hash de personne existant, tag lisible, année, lieu) ; vide : « Aucune expérience proche trouvée. »
- panneau replié : summary « Réglages et événements non classés » ; « N actes d'état civil écartés d'office » et « N événements sans date ».
- export : bouton « Expériences proches (CSV) », phrase « Personnes ayant vécu une expérience proche (non enregistré dans le fichier compagnon). »
- Stats : carte « Expériences proches : N » liée à `#/organisations`, à côté de « Organisations candidates ».
- `NAMED_FROM_LABELS.address = 'Adresse'`.

Chargement : les expériences se chargent avec la liste des organisations (même séquence anti-course que `_orgsSeq`), sont invalidées dans les mêmes cas que `state.organizations.loaded` (nouvelle session, écriture, changement de mots ignorés), et ne dépendent pas des filtres ni de la pagination des organisations.

- [ ] **Step 1: Écrire les tests qui échouent** dans `test_static_frontend.py` : présence des identifiants ci-dessus dans `index.html`, de `'/api/v1/organizations/shared-experiences'` et de `shared-experiences-csv` dans `app.js`, de la phrase « Ce n'est pas une appartenance à une organisation. », et absence du mot « membres » dans le gabarit des cartes d'expérience (rechercher la fonction de rendu, par ex. `renderSharedExperiences`, et vérifier que son corps ne contient pas « membre »).
- [ ] **Step 2: Lancer** `COLUMNS=250 uv run python -m pytest tests/api/test_static_frontend.py -q` → échec.
- [ ] **Step 3: Implémenter** HTML, JS (fonctions `loadSharedExperiences()` et `renderSharedExperiences(data)`), CSS dans le style existant ; tout texte venant de l'API passe par `escHtml`.
- [ ] **Step 4: Vérifier** : tests verts, `node --check core/src/geneweb_py/api/static/app.js` ; puis lancer l'API (`uv run python run_api.py`) sur une **fixture synthétique** et contrôler dans le navigateur : deux sections, panneau replié, une carte dépliée, téléchargement CSV, carte Stats, aucune erreur console. Arrêter le serveur ensuite.
- [ ] **Step 5: Commit** `feat(webapp): shared experiences section and settings panel in the organizations tab`.

---

### Task 6: Documentation et validation sur la base réelle

**Files:**
- Modify: `README.md`, `README.en.md` (paragraphe de l'onglet Organisations, ~l.230-240 : retirer « par défaut recensement et domicile »)
- Modify: `core/doc/organizations_candidates_design.md` (renvoi vers la nouvelle spec en tête du § 3.3 et du § 3.9)
- Modify: `core/AGENTS.md` (ligne `shared_experiences.py` dans l'arborescence `core/`)

- [ ] **Step 1: Rédiger** : README FR/EN — deux sections, état civil écarté d'office, organisations à signal fort (dont adresses), expériences proches (proximité et non appartenance, non enregistrées, export `experiences_proches.csv`) ; renvois dans la spec du chantier A ; ligne d'architecture.
- [ ] **Step 2: Valider sur la base réelle**, en local, lecture seule, avec un script jetable dans le répertoire scratchpad (jamais dans le dépôt) : nombre de candidates, de candidates « adresse », `civil_status_total`, nombre d'expériences par thème, `undated_total`. Rapporter **les comptes seulement** à l'auteur ; comparer aux ordres de grandeur du § 2 de la spec.
- [ ] **Step 3: Lancer** toute la suite, ruff (check et format), mypy, `uv lock --check` → tout passe.
- [ ] **Step 4: Commit** `docs: shared experiences and probable organizations`.
