# Atelier : arrondissements de Paris, Lyon et Marseille (étape 2), plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** reconnaître les arrondissements de Paris (12 anciens, 20 actuels), Lyon et Marseille comme niveaux de lieu, et dater l'arrondissement de chaque occurrence (code, numéro, rue), avec une liste des précisions à trancher et leur export.

**Architecture :** une table d'arrondissements pure Python (`refdata/arrondissements.py`) donne codes, numéros et périodes. La décomposition détache le numéro écrit (« Paris 7e ») et lit les codes INSEE d'arrondissement ; `rule_levels` ajoute un niveau `arrondissement` sous la commune, ce qui en fait un lieu distinct (`insee:75056|7e arrondissement`) par le mécanisme de l'étape 1 (`finer_key`). Une table parisienne des rues (ODbL, construite une fois par `atelier/tools/build_paris.py`) sert au moteur de précisions (`places/precision.py`), qui résout chaque occurrence selon sa date ; les choix de l'utilisateur sont stockés dans le référentiel (schéma 3).

**Tech Stack :** Python ≥ 3.11, workspace `uv`, SQLite, FastAPI + Pydantic, JavaScript sans framework, pytest, ruff, mypy strict. Outil de construction : `urllib.request` et `json` de la bibliothèque standard, point dans un polygone en Python pur.

**Spec :** `docs/superpowers/specs/2026-11-08-atelier-lieux-niveaux-design.md` (§ 4.1, 6, 9 « Précisions par occurrence », 11 `precisions_occurrences` et `LISEZMOI`, 12, 13 étape 2, 15 « Arrondissements »). L'étape 1 est dans `main` (287f84c) : `Level`, `rule_levels`, `finer_key`, référentiel schéma 2.

## Global Constraints

- Dépôt **public** : fixtures synthétiques uniquement ; noms de communes, de rues et de pays réels permis, aucun nom de personne réelle ; jamais de `*.gw`/`*.ged` réel ; ne jamais lire `_local_testdata/bases/`.
- `git add` avec chemins explicites, puis `git diff --cached --name-only` ; ni `git push`, ni `--force`, ni étiquette `atelier-v*` sans accord explicite. Travail sur la branche `feat/atelier-arrondissements`, jamais sur `main`.
- `uv` exclusivement. Tests : `uv run --package prosopo-gw-atelier python -m pytest atelier`. Lint : `uv run --package prosopo-gw-atelier ruff check atelier/src atelier/tests atelier/tools` et `ruff format --check` sur les mêmes chemins. Types : `uv run --package prosopo-gw-atelier mypy --config-file atelier/pyproject.toml atelier/src/prosopo_gw_atelier`.
- Code, identifiants et messages de commit en anglais (`type(scope): message`, terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`) ; textes affichés et documentation en français.
- `core` n'est pas modifié.
- Ordre des indices **(décision de l'auteur)** : 1. le code, 2. le numéro écrit selon la date de l'acte, 3. la rue croisée avec la date. Deux indices qui désignent deux arrondissements : précision **en conflit**, rien n'est tranché en silence.
- Une écriture qui porte un arrondissement forme un cluster et un `lieu_id` distincts de la ville seule.
- Occurrence sans date : numéro sans période. Occurrence datée de l'année de transition (1860 pour Paris) : **incertaine**. Rue qui donne plusieurs candidats : **ambiguë**, jamais devinée.
- Lyon et Marseille n'utilisent que le code et le numéro, pas la rue.
- La table parisienne est livrée dans le paquet, **dans un dossier à part avec sa licence ODbL et sa note d'attribution** (Ville de Paris, consortium ALPAGE et auteurs, GeoHistoricalData), reprise dans le `LISEZMOI` de l'export. Les sources sont téléchargées par l'outil, **jamais versionnées brutes**. Aucune dépendance SIG, ni dans l'outil ni dans l'atelier.
- Valeurs exportées en français ; statuts de précision exportés : `applique`, `conflit`, `incertain`, `ambigu`.

## Choix de ce plan (à relire)

1. **Pas de fichier de données pour les arrondissements eux-mêmes.** Codes et numéros suivent une règle (Paris : INSEE `751NN`, postal `750NN` et `75116` ; Lyon : `6938N`, `6900N` ; Marseille : `132NN`, `130NN`) ; le module `refdata/arrondissements.py` les calcule et porte les dates de création. Le constructeur vérifie ces dates (spec § 6.1) à la Task 1 et cite sa source dans la docstring.
2. **Identifiant du niveau.** Paris : toujours le numéro seul, `paris-07`, même quand l'écriture porte un code (le code n'est qu'un indice par occurrence) ; nom `7e arrondissement` (`1er arrondissement` pour le premier). Lyon et Marseille : le code INSEE d'arrondissement (`69381`), origine `insee`, source `COG <millésime>`. Ainsi « Paris 7e », « Paris, VIIe arr. » et « 75007 Paris » tombent dans le même cluster `insee:75056|7e arrondissement` (clé de nom du niveau 0, `finer_key` de l'étape 1).
3. **Identifiants des précisions** : ancien arrondissement `paris-1795-07`, arrondissement actuel de Paris `75107`, de Lyon `69381`, de Marseille `13201` ; quartier d'avant 1860 : l'identifiant ALPAGE ; quartier actuel : `paris-q-<numéro INSEE du quartier>` si la source le donne, sinon le nom normalisé préfixé `paris-q-`.
4. **Périodes** (clé des décisions et colonne d'export) : `paris-1795` (avant 1860), `paris-1860` (1860 et après), `lyon`, `marseille`, et `""` pour une occurrence sans date. L'année vient des colonnes `*_annee` des tables de `core` (nouveau champ `Occurrence.year`).
5. **Incertain** : année égale à 1860 à Paris ; date approximative (`~`, `?`, `<`, `>`, `..`, `|` dans le texte) dont l'année tombe entre 1859 et 1861 ; occurrence d'avant la création de l'arrondissement à Lyon ou Marseille ; code d'arrondissement sur une occurrence d'avant 1860 (le code désigne l'arrondissement actuel, pas celui de la date).
6. **Où vivent les décisions** : table `precisions` du référentiel, clé `(writing, complement, period)` (complément vide = `""`), valeurs `arrondissement_id`, `quartier_id` (l'un ou l'autre peut être vide ; les deux vides = « aucun arrondissement »), `project`, `decided_at`. Schéma 3 ; un fichier en schéma 2 reçoit la table à l'ouverture, sans sauvegarde ni entrée de journal (aucune donnée ne change). La montée est **générique** : pour un fichier dont `user_version` est entre 2 et `SCHEMA_VERSION - 1`, rejouer `schema.sql` (uniquement des `CREATE … IF NOT EXISTS`) puis écrire `user_version` ; les étapes 3 et 4 ajouteront leurs tables par ce même chemin. Journal et annulation par le mécanisme générique (`_TABLES`).
7. **Précisions sans conflit** : calculées à la volée, jamais stockées ; une décision stockée prime sur le calcul et passe le statut à `applique` avec l'indice `manuel`.
8. **Export JSON du référentiel** : reste `"version": 2`, avec une liste facultative `precisions` (absente = vide). Le paquet n'est pas encore publié, aucun lecteur ancien n'est à ménager.
9. **Lieux v1 et v2 de Paris (spec § 12).** Une écriture déjà rattachée à un lieu « Paris » sans arrondissement, et qui en nomme un, est signalée dans `historical_writings` (« nomme le 7e arrondissement ») ; l'utilisateur la scinde et la valide à part avec les gestes existants. Rien ne change en silence. Coût : pas de proposition automatique de niveau sur le lieu, qui mêle souvent plusieurs arrondissements.
10. **Rue** : lue dans le complément de l'occurrence, à partir du premier mot de voie (`rue`, `boulevard`, `avenue`, `place`, `quai`, `impasse`, `passage`, `faubourg`, `cours`, `allee`, `chaussee`, `cite`, `villa`, `square`, `pont`, `port`, `chemin`, `route`, `ruelle`, `cul-de-sac`, `carrefour`, `marche`, `parvis`, `promenade`, `sentier`, `galerie`, `cloitre`, `enclos`, `cour`) et jusqu'à la virgule suivante. Une écriture « Paris » sans numéro peut recevoir un arrondissement par sa rue.
11. **Repli (spec § 6.4)** : si les couches ArcGIS Vasserot ne répondent pas à la Task 5, la table sort sans rues ni quartiers d'avant 1860 ; le rapport de la Task 5 le dit et `docs/reflexions/points-ouverts.md` le consigne.

## Review Focus

- **Complément d'adresse réel et abrégé** (`12, r. St-Honoré`, `bd. Saint Germain`, `rue de la Paix n° 5`, `faub. St Antoine`) : la rue est reconnue sous sa forme normalisée. → Task 3, `test_street_key_abbreviations`.
- **Numéro hors de la ville ou hors bornes** (`Paris 25e`, `Toulouse 3e`, `Marseille 17e`, `Lyon 10e`) : aucun arrondissement, aucune exception, la décomposition reste celle de l'étape 1. → Task 2, `test_out_of_range_numbers_are_not_arrondissements`.
- **Date approximative autour de 1860** (`~1860`, `<1861`, `1858..1862`) : précision incertaine, jamais appliquée d'office. → Task 6, `test_approximate_date_near_transition_is_uncertain`.
- **Référentiel de l'étape 1 (schéma 2) ou v1 rouvert** : passe en schéma 3 sans perte de lieu, de niveau ni de décision ; une seconde ouverture ne refait rien. → Task 7, `test_schema2_file_is_upgraded_in_place`, `test_v1_file_migrates_to_schema3`.
- **Grosse base parisienne** (des dizaines de milliers d'occurrences de « Paris ») : le calcul des précisions est fait une fois par chargement (cache invalidé comme celui des clusters), sans requête par occurrence. → Task 8, `test_precisions_are_cached_until_reload`.

---

## Fichiers

| Fichier | Rôle | Tâches |
|---|---|---|
| `atelier/src/prosopo_gw_atelier/refdata/arrondissements.py` | arrondissements, codes, périodes | 1 |
| `atelier/src/prosopo_gw_atelier/places/decompose.py` | numéro et code d'arrondissement | 2 |
| `atelier/src/prosopo_gw_atelier/places/model.py` | `Decomposition.arrondissement`, `Occurrence.year` | 2, 6 |
| `atelier/src/prosopo_gw_atelier/places/levels.py` | niveau `arrondissement` | 2 |
| `atelier/src/prosopo_gw_atelier/places/streets.py` | rue lue dans un complément, clé de rue | 3 |
| `atelier/tools/build_paris.py` | construction de la table parisienne | 4 |
| `atelier/src/prosopo_gw_atelier/refdata/paris/` | table livrée, `LICENCE.txt`, `ATTRIBUTION.txt`, `VERSION` | 5 |
| `atelier/src/prosopo_gw_atelier/refdata/paris_table.py` | chargeur de la table parisienne | 5 |
| `atelier/src/prosopo_gw_atelier/places/precision.py` | moteur de précisions | 6 |
| `atelier/src/prosopo_gw_atelier/places/collect.py` | année de l'occurrence | 6 |
| `atelier/src/prosopo_gw_atelier/store/registry.py`, `schema.sql`, `exchange.py`, `migrate.py` | table `precisions`, schéma 3 | 7 |
| `atelier/src/prosopo_gw_atelier/project.py` | précisions du projet, écritures à scinder | 8 |
| `atelier/src/prosopo_gw_atelier/export/pivot.py`, `LISEZMOI.txt`, `archive.py` | `precisions_occurrences`, attributions | 9 |
| `atelier/src/prosopo_gw_atelier/web/app.py`, `schemas.py` | API des précisions | 10 |
| `atelier/src/prosopo_gw_atelier/web/static/app.js`, `style.css`, `index.html` | onglet Précisions | 11 |
| `atelier/README.md`, `atelier/doc/design_v1.md`, `docs/reflexions/points-ouverts.md` | documentation | 12 |

---

### Task 1 : table des arrondissements

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/refdata/arrondissements.py`
- Modify: `atelier/src/prosopo_gw_atelier/refdata/__init__.py` (réexport)
- Test: `atelier/tests/refdata/test_arrondissements.py`

**Interfaces:**
- Produces:
  - `City = Literal["paris", "lyon", "marseille"]` ; `CITY_INSEE: dict[City, str] = {"paris": "75056", "lyon": "69123", "marseille": "13055"}`.
  - `@dataclass(frozen=True) class Arrondissement: id: str; city: City; number: int; name: str; start: str; end: str | None` (`start`/`end` en ISO `AAAA-MM-JJ`).
  - `city_of(insee: str) -> City | None` (code de la commune).
  - `level_id(city: City, number: int) -> str` : `paris-07` pour Paris, code INSEE d'arrondissement (`69381`, `13201`) pour Lyon et Marseille.
  - `level_name(number: int) -> str` : `1er arrondissement`, `7e arrondissement`.
  - `current(city: City, number: int) -> Arrondissement | None` ; `former_paris(number: int) -> Arrondissement | None` (1 à 12, `paris-1795-NN`).
  - `by_code(code: str) -> tuple[City, int] | None` : INSEE d'arrondissement (`75107`, `69381`, `13201`) ou postal (`75007`, `75116` → 16, `69001`, `13001`).
  - `numbers(city: City) -> range` : Paris 1-20, Lyon 1-9, Marseille 1-16.

- [ ] **Step 1 : vérifier les dates.** Dates de création à confirmer sur une source publique (Légifrance, INSEE, Archives municipales) : anciens arrondissements de Paris 1795-10-11 au 1859-12-31 ; actuels de Paris depuis 1860-01-01 ; Lyon 1er à 5e 1852-03-24, 6e 1867-03-08, 7e 1912-07-08, 8e 1959-07-12, 9e 1964-02-12 ; Marseille 1er à 16e 1946-03-12. Corriger une date infirmée et citer la source dans la docstring du module. Ne pas versionner de document téléchargé.

- [ ] **Step 2 : tests qui échouent**

```python
def test_codes_read_both_ways():
    assert by_code("75107") == ("paris", 7)
    assert by_code("75007") == ("paris", 7)
    assert by_code("75116") == ("paris", 16)
    assert by_code("69001") == ("lyon", 1)
    assert by_code("13216") == ("marseille", 16)
    assert by_code("75021") is None and by_code("69010") is None and by_code("59350") is None

def test_level_ids_and_names():
    assert level_id("paris", 7) == "paris-07"
    assert level_id("lyon", 1) == "69381"
    assert level_name(1) == "1er arrondissement" and level_name(7) == "7e arrondissement"

def test_periods():
    assert former_paris(7).id == "paris-1795-07" and former_paris(7).end == "1859-12-31"
    assert former_paris(13) is None
    assert current("paris", 7).id == "75107" and current("paris", 7).start == "1860-01-01"
    assert current("lyon", 8).start == "1959-07-12"
    assert city_of("13055") == "marseille" and city_of("59350") is None
```

- [ ] **Step 3 : lancer** `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/refdata/test_arrondissements.py -v` → échec à l'import.
- [ ] **Step 4 : implémenter** le module (constantes, pas de fichier de données).
- [ ] **Step 5 : relancer** → PASS ; ruff et mypy propres.
- [ ] **Step 6 : commit** `feat(atelier): add the Paris, Lyon and Marseille arrondissement table`.

---

### Task 2 : la décomposition lit l'arrondissement, la chaîne le porte

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/places/model.py`, `places/decompose.py`, `places/levels.py`
- Test: `atelier/tests/places/test_decompose.py`, `atelier/tests/places/test_levels.py`, `atelier/tests/places/test_cluster.py`
- Fixture: `atelier/tests/fixtures/make_refdata_mini.py` + `refdata_mini/*.csv.gz` régénérés (ajouter Paris `75056` et Marseille `13055` avec leurs codes postaux `75001`-`75020`, `75116`, `13001`-`13016`)

**Interfaces:**
- Consumes: Task 1 (`by_code`, `city_of`, `numbers`, `level_id`, `level_name`).
- Produces:
  - `ElementKind` gagne `"arrondissement"` ; hints `HINT_ARR_NUMBER = "numéro d'arrondissement"`, `HINT_ARR_CODE = "code d'arrondissement"`.
  - `@dataclass(frozen=True) class WrittenArrondissement: city: City; number: int; clue: Literal["code", "number"]` dans `places/model.py` ; champ `Decomposition.arrondissement: WrittenArrondissement | None = None`. Si l'écriture porte à la fois un code et un numéro qui s'accordent, `clue = "code"` ; s'ils se contredisent, l'arrondissement du code est gardé et le numéro devient un niveau sans type (le conflit apparaîtra par occurrence, Task 6).
  - `split_arrondissement(segment: str) -> tuple[str, int] | None` dans `decompose.py` : reconnaît `7e`, `7è`, `7ème`, `7eme`, `1er`, `1re`, `1ère`, `VIIe`, `VII`, `7e arr.`, `7e arrondissement`, `arrondissement 7`, avant ou après le nom (`Paris 7e`, `7e arrondissement de Paris`, `Paris (7e)` est déjà découpé sur les parenthèses) ; rend le reste nettoyé et le numéro, ou `None`.
  - `rule_levels` : quand `decomposition.arrondissement` est là et que la commune résolue est sa ville, un niveau `Level(type="arrondissement", name=level_name(n), identifier=level_id(city, n), written=<texte écrit s'il diffère>)` vient juste avant la commune ; origine `rule` (Paris) ou `insee` avec `source=f"COG {ref.cog_vintage}"` (Lyon, Marseille).

Règles : un code INSEE d'arrondissement (`75107`) est lu comme INSEE de sa ville (il n'est plus `ambiguous`) ; un code postal d'arrondissement garde sa lecture actuelle (commune) et ajoute l'arrondissement ; un numéro n'est retenu que si le reste du segment (ou un autre segment) résout la commune sur l'une des trois villes et si le numéro est dans `numbers(city)`. Sinon le segment est lu exactement comme à l'étape 1.

- [ ] **Step 1 : tests qui échouent**

```python
def test_paris_number_forms(ref):
    for writing in ("Paris 7e", "Paris, 7ème arrondissement", "Paris (VIIe arr.)", "7e arrondissement de Paris"):
        d = decompose(writing, ref)
        assert d.insee == "75056", writing
        assert d.arrondissement == WrittenArrondissement("paris", 7, "number"), writing

def test_arrondissement_codes(ref):
    assert decompose("75107", ref).arrondissement == WrittenArrondissement("paris", 7, "code")
    assert decompose("75107", ref).ambiguous is False
    assert decompose("75007 Paris", ref).arrondissement == WrittenArrondissement("paris", 7, "code")
    assert decompose("13008 Marseille", ref).arrondissement == WrittenArrondissement("marseille", 8, "code")

def test_out_of_range_numbers_are_not_arrondissements(ref):
    for writing in ("Paris 25e", "Lyon 10e", "Marseille 17e", "Merville 3e"):
        d = decompose(writing, ref)
        assert d.arrondissement is None, writing

def test_postal_code_of_municipal_arrondissement_maps_to_commune(ref):  # revu (spec § 15)
    d = decompose("69001 Lyon", ref)
    assert d.insee == "69123"
    assert d.arrondissement == WrittenArrondissement("lyon", 1, "code")
    chain = rule_levels(d, ref)
    assert [(l.type, l.name, l.identifier) for l in chain[:2]] == [
        ("arrondissement", "1er arrondissement", "69381"), ("commune", "Lyon", "69123")]
```

Dans `test_levels.py` : `test_paris_arrondissement_level` (`Paris 7e` → rangs 0 `7e arrondissement` / `paris-07` / origine `rule`, 1 `Paris`, puis département, région, pays). Dans `test_cluster.py` : `test_arrondissement_is_a_distinct_cluster` (`Paris`, `Paris 7e`, `75007 Paris` → deux clusters, `insee:75056` et `insee:75056|7e arrondissement`, ce dernier avec les deux écritures).

- [ ] **Step 2 : lancer** `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/places -v` → les nouveaux tests échouent.
- [ ] **Step 3 : implémenter** (`split_arrondissement` avec une expression régulière par forme ; les chiffres romains de I à XX).
- [ ] **Step 4 : relancer toute la suite** → PASS (les autres tests de l'étape 1 inchangés, sauf le test revu ci-dessus).
- [ ] **Step 5 : commit** `feat(atelier): read written arrondissements as a level of the place`.

---

### Task 3 : rue lue dans un complément

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/places/streets.py`
- Test: `atelier/tests/places/test_streets.py`

**Interfaces:**
- Produces:
  - `street_of(complement: str | None) -> str | None` : le texte de la voie (choix 10), sans numéro de maison ni « n° ».
  - `street_key(street: str) -> str` : minuscules, diacritiques retirés (`refdata.normalize`), abréviations développées (`r.`→`rue`, `bd`/`boul.`/`bould`→`boulevard`, `av.`→`avenue`, `pl.`→`place`, `fg`/`faub.`/`fbg`→`faubourg`, `q.`→`quai`, `imp.`→`impasse`, `pass.`→`passage`, `st`→`saint`, `ste`→`sainte`), traits d'union et apostrophes en espaces, articles retirés (`de`, `du`, `des`, `de la`, `de l`, `d`, `la`, `le`, `les`, `l`) sauf en tête, espaces réduits. Le même code sert à l'outil (Task 4) et à l'atelier.

- [ ] **Step 1 : tests qui échouent**

```python
def test_street_of_complement():
    assert street_of("12, rue Saint-Honoré") == "rue Saint-Honoré"
    assert street_of("chez son père, 5 rue de la Paix, 2e étage") == "rue de la Paix"
    assert street_of("hôpital de la Charité") is None
    assert street_of(None) is None

def test_street_key_abbreviations():
    assert street_key("12 r. St-Honoré") == street_key("rue Saint-Honoré") == "rue saint honore"
    assert street_key("bd. Saint Germain") == "boulevard saint germain"
    assert street_key("faub. St Antoine") == street_key("rue du Faubourg-Saint-Antoine").removeprefix("rue ")
    assert street_key("rue de la Paix n° 5") == "rue paix"
```

- [ ] **Step 2 : lancer** → échec.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): read and normalize the street of an occurrence complement`.

Note : `rue du Faubourg-Saint-Antoine` et `faubourg Saint-Antoine` ne donnent pas la même clé ; la table (Task 4) enregistre aussi, pour chaque voie dont le nom commence par `rue du faubourg`, la clé sans `rue`. Le test ci-dessus le fixe côté clé.

---

### Task 4 : outil de construction de la table parisienne

**Files:**
- Create: `atelier/tools/build_paris.py`
- Create: `atelier/tests/fixtures/paris_sources/` : `vasserot_quartiers.geojson`, `vasserot_roads.geojson`, `voies_actuelles.json`, `voies_caduques.json` (synthétiques, 3 à 6 objets chacun, noms de rues réels permis, géométries inventées)
- Test: `atelier/tests/refdata/test_build_paris.py`

**Interfaces:**
- Consumes: Task 3 (`street_key`), Task 1 (`former_paris`, `current`).
- Produces (format de la table, lu par la Task 5) :
  - `rues.csv.gz` : `cle;periode;arrondissement_id;quartier_id;quartier` (une ligne par couple rue × arrondissement × quartier ; `periode` `paris-1795` ou `paris-1860`).
  - `quartiers.csv.gz` : `id;nom;arrondissement_id;periode`.
  - `communes_annexees.csv.gz` : `nom;arrondissement_ids` (identifiants séparés par `|`), les communes annexées en 1860 : Auteuil, Passy, Batignolles-Monceau, Montmartre, La Chapelle, La Villette, Belleville, Charonne, Bercy, Vaugirard, Grenelle (le constructeur vérifie la liste et les arrondissements d'accueil).
  - `VERSION` : `extraction=<AAAA-MM-JJ>` puis une ligne `source=<url>` par source.
  - Fonctions testables : `point_in_polygon(x: float, y: float, rings: list[list[tuple[float, float]]]) -> bool` (règle pair-impair, trous compris) ; `midpoint(line: list[tuple[float, float]]) -> tuple[float, float]` (point à mi-longueur) ; `build(sources: Path, output: Path, extracted: date) -> None` ; `fetch(output: Path) -> None` (réseau, non testé).

Sources (spec § 6.4) :
- quartiers Vasserot : `https://services.arcgis.com/ak2bo87wLfUpMrt1/ArcGIS/rest/services/VasserotQuartiers_1790to1860/FeatureServer/1/query?where=1%3D1&outFields=*&f=geojson` (48 objets) ;
- rues Vasserot : `.../VasserotRoads_1810to1836/FeatureServer/1/query?...&f=geojson` (4 368 tronçons, nom dans `NOM_ENTIER`), paginé par `resultOffset` / `resultRecordCount` ;
- voies actuelles : `https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/denominations-emprises-voies-actuelles/exports/json` (`typo_min`, `arrdt` liste comme `["11e"]`, `quartier` liste) ;
- voies caduques : `.../denominations-des-voies-caduques/exports/json` (`typo_min`, `arrdt` texte, `quartier`, `date_arret`) ; une voie caduque supprimée avant 1860 est ignorée.

Règles : un tronçon Vasserot est rattaché au quartier qui contient son milieu ; hors de tout quartier, il est ignoré et compté. Une voie actuelle ou caduque donne une ligne par arrondissement de `arrdt` (`11e` → `75111`) et par quartier. Une clé présente sous plusieurs arrondissements d'une même période garde toutes ses lignes (la précision sera ambiguë).

- [ ] **Step 1 : lire les métadonnées** des deux couches ArcGIS (`.../FeatureServer/1?f=json`) et noter les champs du nom de quartier, de son identifiant et de son arrondissement ; les reporter dans la docstring de l'outil et dans les fixtures synthétiques. Si les couches ne répondent pas, appliquer le choix 11 et le dire dans le rapport.
- [ ] **Step 2 : tests qui échouent**

```python
def test_point_in_polygon_with_hole():
    outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]
    assert point_in_polygon(1, 1, [outer, hole])
    assert not point_in_polygon(5, 5, [outer, hole])

def test_build_from_synthetic_sources(tmp_path):
    build(FIXTURES / "paris_sources", tmp_path, date(2026, 11, 8))
    rows = read_gz_csv(tmp_path / "rues.csv.gz")
    assert {"cle": "rue saint honore", "periode": "paris-1795", "arrondissement_id": "paris-1795-04", ...} <= ...  # selon les fixtures
    assert any(r["periode"] == "paris-1860" and r["arrondissement_id"] == "75111" for r in rows)
    assert "extraction=2026-11-08" in (tmp_path / "VERSION").read_text()

def test_segment_outside_any_quartier_is_dropped(tmp_path): ...
def test_street_in_two_arrondissements_keeps_both_rows(tmp_path): ...
```

Le constructeur écrit les valeurs exactes attendues à partir de ses fixtures ; chaque test vérifie une règle ci-dessus.

- [ ] **Step 3 : lancer** → échec.
- [ ] **Step 4 : implémenter** `build` et `fetch` (`urllib.request`, en-tête `User-Agent: prosopo-gw-atelier build_paris`, délai d'une seconde entre deux pages). `main()` : `fetch` dans un dossier temporaire hors dépôt, puis `build` vers `--output`.
- [ ] **Step 5 : relancer** → PASS.
- [ ] **Step 6 : commit** `feat(atelier): add the Paris street table build tool`.

---

### Task 5 : table parisienne livrée et son chargeur

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/refdata/paris/` : `rues.csv.gz`, `quartiers.csv.gz`, `communes_annexees.csv.gz`, `VERSION`, `LICENCE.txt` (texte de l'ODbL 1.0 ou son résumé avec lien officiel), `ATTRIBUTION.txt`
- Create: `atelier/src/prosopo_gw_atelier/refdata/paris_table.py`
- Modify: `atelier/pyproject.toml` si les données du paquet doivent être déclarées
- Test: `atelier/tests/refdata/test_paris_table.py`, `atelier/tests/fixtures/paris_mini/` (sortie de `build` sur les fixtures de la Task 4)

**Interfaces:**
- Consumes: format de la Task 4.
- Produces:
  - `@dataclass(frozen=True) class StreetHit: arrondissement_id: str; quartier_id: str | None; quartier: str | None`.
  - `class ParisTable` : `streets(key: str, period: str) -> tuple[StreetHit, ...]` ; `annexed(name_key: str) -> tuple[str, ...]` ; `extraction: str` ; `attribution: str` (texte d'`ATTRIBUTION.txt`).
  - `load_paris_table(directory: Path | None = None) -> ParisTable` (mis en cache comme `load_refdata`).

`ATTRIBUTION.txt` nomme : Ville de Paris (dénominations des voies actuelles et caduques, ODbL) ; consortium ALPAGE et ses auteurs (quartiers et rues Vasserot, ODbL) ; GeoHistoricalData (Verniquet, Jacoubet, CC0, si utilisés) ; la date d'extraction.

- [ ] **Step 1 : lancer l'outil** (`uv run --package prosopo-gw-atelier python atelier/tools/build_paris.py --output atelier/src/prosopo_gw_atelier/refdata/paris`) ; noter dans le rapport le nombre de lignes, de tronçons ignorés et la taille du dossier (attendu : moins de 1 Mo compressé ; au-delà, le signaler).
- [ ] **Step 2 : tests qui échouent** sur `paris_mini` : `test_lookup_by_period`, `test_unknown_street_is_empty`, `test_attribution_names_every_source` (`"ALPAGE" in table.attribution and "Ville de Paris" in table.attribution`), et sur la table livrée `test_shipped_table_loads` (au moins 40 quartiers `paris-1795`, `extraction` non vide).
- [ ] **Step 3 : implémenter le chargeur.**
- [ ] **Step 4 : relancer** → PASS ; vérifier que le paquet construit (`uv build --package prosopo-gw-atelier`) contient `refdata/paris/*`.
- [ ] **Step 5 : commit** `feat(atelier): ship the Paris street table with its ODbL licence` (chemins explicites, `git diff --cached --name-only` : aucun fichier brut de source).

---

### Task 6 : précisions par occurrence

**Files:**
- Create: `atelier/src/prosopo_gw_atelier/places/precision.py`
- Modify: `atelier/src/prosopo_gw_atelier/places/model.py` (`Occurrence.year: int | None = None`), `places/collect.py` (année tirée de `naissance_annee`, `deces_annee`, `mariage_annee`, `annee`)
- Test: `atelier/tests/places/test_precision.py`, `atelier/tests/places/test_collect.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5 ; `Level`.
- Produces:
  - `PrecisionStatus = Literal["applied", "conflict", "uncertain", "ambiguous"]` ; `Clue = Literal["code", "number", "street", "manual"]`.
  - `@dataclass(frozen=True) class Candidate: arrondissement_id: str; quartier_id: str | None; quartier: str | None; clue: Clue`.
  - `@dataclass(frozen=True) class Precision: period: str; status: PrecisionStatus; candidates: tuple[Candidate, ...]` (`applied` : exactement un candidat).
  - `period_of(city: City, year: int | None) -> str` (choix 4).
  - `precise(levels: Sequence[Level], arrondissement: WrittenArrondissement | None, occurrence: Occurrence, table: ParisTable) -> Precision | None` : `None` hors des trois villes (pas de niveau `commune` de code `75056`, `69123`, `13055`) ou sans aucun indice.

Règles (en plus des choix 4 et 5) :
- numéro Paris + `paris-1795` → `paris-1795-NN` (numéro 13 à 20 avant 1860 : conflit avec un candidat vide, le numéro n'existait pas) ; numéro + `paris-1860` → `751NN` ; numéro sans date → candidat `paris-NN`, statut `applied`.
- code → arrondissement actuel ; avant 1860 : `uncertain`.
- rue → toutes les lignes de la table pour la période ; une seule → candidat avec quartier ; plusieurs arrondissements → `ambiguous` ; sans date, la rue n'est pas lue.
- deux indices qui désignent deux arrondissements différents → `conflict` avec les deux candidats ; s'ils s'accordent, le quartier de la rue complète le candidat du code ou du numéro.

- [ ] **Step 1 : tests qui échouent** (spec § 15)

```python
def test_same_number_in_1850_and_1870(table):
    levels = rule_levels(decompose("Paris 7e", ref), ref)
    arr = WrittenArrondissement("paris", 7, "number")
    p1850 = precise(levels, arr, occ(year=1850), table)
    p1870 = precise(levels, arr, occ(year=1870), table)
    assert (p1850.status, p1850.candidates[0].arrondissement_id) == ("applied", "paris-1795-07")
    assert (p1870.status, p1870.candidates[0].arrondissement_id) == ("applied", "75107")

def test_postal_code_and_street_in_conflict(table):  # code du 7e, rue du 15e (fixture)
    p = precise(levels_7e, WrittenArrondissement("paris", 7, "code"), occ(year=1900, complement="rue de Vaugirard"), table)
    assert p.status == "conflict"
    assert {c.clue for c in p.candidates} == {"code", "street"}

def test_undated_occurrence_keeps_number_without_period(table):
    p = precise(levels_7e, arr7, occ(year=None), table)
    assert (p.period, p.status, p.candidates[0].arrondissement_id) == ("", "applied", "paris-07")

def test_street_that_changed_arrondissement(table):  # même clé, 1795 → paris-1795-04, 1860 → 75101 (fixture)
    ...

def test_transition_year_is_uncertain(table): ...           # year=1860
def test_approximate_date_near_transition_is_uncertain(table): ...  # date="~1860", year=1860 ; date="1858..1862", year=1858
def test_plain_paris_gets_arrondissement_from_street(table): ...
def test_lyon_ignores_street_and_dates_before_creation(table): ...  # Lyon 8e en 1950 → uncertain
def test_outside_the_three_cities_is_none(table): ...
```

Dans `test_collect.py` : `test_occurrence_year_from_core_year_columns`.

- [ ] **Step 2 : lancer** → échec.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 : relancer la suite** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): date the arrondissement of each occurrence`.

---

### Task 7 : décisions de précision dans le référentiel (schéma 3)

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/store/schema.sql`, `store/registry.py`, `store/migrate.py`, `store/exchange.py`
- Test: `atelier/tests/store/test_registry.py`, `test_migrate.py`, `test_exchange.py`

**Interfaces:**
- Consumes: `Candidate`, `Clue` (Task 6).
- Produces:
  - `SCHEMA_VERSION = 3` ; table `precisions(writing TEXT, complement TEXT, period TEXT, arrondissement_id TEXT, quartier_id TEXT, project TEXT, decided_at TEXT, PRIMARY KEY (writing, complement, period))` ajoutée à `_TABLES` (journal et annulation génériques).
  - `@dataclass(frozen=True) class PrecisionDecision: writing: str; complement: str; period: str; arrondissement_id: str | None; quartier_id: str | None; project: str | None; decided_at: str`.
  - `PlaceRegistry.decide_precision(writing: str, complement: str | None, period: str, arrondissement_id: str | None, quartier_id: str | None, project: str) -> int | None` (une entrée de journal `correct`, charge utile `{"kind": "precision", …}` : la contrainte `CHECK` de la colonne `action` ne change pas) ; `PlaceRegistry.precision_decisions() -> dict[tuple[str, str, str], PrecisionDecision]` ; `PlaceRegistry.clear_precision(writing, complement, period, project) -> int | None`.
  - Échange : `export_registry` ajoute `"precisions": [...]` (clés françaises `ecriture`, `complement`, `periode`, `arrondissement_id`, `quartier_id`) ; l'import l'accepte absente.

- [ ] **Step 1 : tests qui échouent** : `test_decide_precision_round_trip`, `test_undo_precision_decision`, `test_schema2_file_is_upgraded_in_place` (un fichier schéma 2 construit avec le code de l'étape 1 garde lieux, niveaux et décisions, `user_version` vaut 3, aucune entrée de journal ajoutée, seconde ouverture sans effet), `test_v1_file_migrates_to_schema3`, `test_export_import_precisions`, `test_import_without_precisions_key`.
- [ ] **Step 2 : lancer** → échec.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 : relancer la suite** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): store arrondissement precision decisions in the registry`.

---

### Task 8 : le projet calcule les précisions

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/project.py`
- Test: `atelier/tests/test_project.py` (fixture `.gw` synthétique : personnes fictives nées à `Paris 7e` en 1850 et 1870, à `Paris [12 rue Saint-Honoré]` en 1820, `75007 Paris [rue de Vaugirard]` en 1900, `Paris 7e` sans date)

**Interfaces:**
- Consumes: Tasks 6, 7 ; `Project.writings`, `Decomposition`, chaînes des clusters.
- Produces:
  - `@dataclass(frozen=True) class OccurrencePrecision: occurrence: Occurrence; writing: str; place_id: str | None; precision: Precision` (statut `applied` avec indice `manual` quand une décision stockée s'applique).
  - `Project.precisions() -> list[OccurrencePrecision]` (toutes les occurrences qui ont une précision, triées par écriture, complément, période, table, ligne) ; `Project.precision_groups(statuses: Collection[PrecisionStatus]) -> list[PrecisionGroup]` avec `PrecisionGroup(writing, complement, period, status, candidates, occurrences: int)`.
  - `ClusterView.historical_writings` signale aussi une écriture qui nomme un arrondissement rattachée à un lieu sans niveau `arrondissement` (valeur : `level_name(n)`, choix 9).
  - Cache : calculé avec le regroupement ; invalidé par `reload`, une décision de précision ou un changement de chaîne.

- [ ] **Step 1 : tests qui échouent** : `test_precisions_of_fixture` (les cinq cas ci-dessus, statuts attendus `applied`, `applied`, `applied` par la rue, `conflict`, `applied` sans période), `test_stored_decision_wins`, `test_precision_groups_gather_same_value`, `test_paris_place_flags_arrondissement_writings`, `test_precisions_are_cached_until_reload` (compteur d'appels à `precise` via `monkeypatch`).
- [ ] **Step 2 : lancer** → échec.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 : relancer la suite** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): compute occurrence precisions in the project`.

---

### Task 9 : export `precisions_occurrences` et attributions

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/export/pivot.py`, `export/LISEZMOI.txt`, `export/archive.py`
- Test: `atelier/tests/export/test_pivot.py`, `test_archive.py`

**Interfaces:**
- Consumes: `Project.precisions()` (Task 8), `ParisTable.attribution`, `ParisTable.extraction`.
- Produces: table `precisions_occurrences` après `niveaux_lieux` : `table`, `ligne_id`, `colonne`, `lieu_id`, `periode`, `arrondissement`, `arrondissement_id`, `quartier`, `quartier_id`, `indice` (`code`, `numero`, `rue`, `manuel`), `statut` (`applique`, `conflit`, `incertain`, `ambigu`). Pour `conflit` et `ambigu`, une ligne par candidat. `build_pivot` reçoit les précisions en paramètre (`precisions: Sequence[OccurrencePrecision] = ()`).

`LISEZMOI.txt` gagne un paragraphe « Arrondissements » (périodes, statuts, une ligne par candidat en cas de conflit) et, sous « Référentiels », l'attribution de la table parisienne avec sa date d'extraction et la licence ODbL.

- [ ] **Step 1 : tests qui échouent** : `test_precisions_table_present`, `test_conflict_gives_one_row_per_candidate`, `test_readme_attributes_paris_table` (`"ODbL" in readme and "ALPAGE" in readme`).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): export occurrence precisions and the Paris attribution`.

---

### Task 10 : API des précisions

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/web/app.py`, `web/schemas.py`
- Test: `atelier/tests/web/test_api.py`

**Interfaces:**
- Consumes: Tasks 7, 8.
- Produces:
  - `GET /api/precisions?status=conflict&status=uncertain&status=ambiguous` → `{"groups": [PrecisionGroupOut]}` ; `PrecisionGroupOut(writing, complement, period, period_label, status, candidates: list[CandidateOut], occurrences)` ; `CandidateOut(arrondissement_id, arrondissement, quartier_id, quartier, clue)` avec libellés français (`period_label` : « avant 1860 », « depuis 1860 », « sans date », « Lyon », « Marseille »).
  - `POST /api/precisions/decide` corps `{writing, complement, period, arrondissement_id, quartier_id}` → `{"entry_id": int | null}` ; 400 en français si `arrondissement_id` n'est ni vide ni l'un des candidats du groupe.
  - L'annulation passe par `POST /api/undo` existant.
  - `ClusterDetail` gagne `arrondissement_writings` uniquement si le schéma existant ne peut pas porter le signal par `historical_writings` (le réutiliser de préférence).

- [ ] **Step 1 : tests qui échouent** : `test_list_precision_groups`, `test_decide_precision_then_undo`, `test_decide_rejects_unknown_candidate`.
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : commit** `feat(atelier): add the precision API`.

---

### Task 11 : onglet Précisions

**Files:**
- Modify: `atelier/src/prosopo_gw_atelier/web/static/app.js`, `style.css`, `index.html`
- Test: `atelier/tests/web/test_static.py`

Écran : un troisième onglet « Précisions » à côté de « Lieux » et « Référentiel ». Une liste de groupes (écriture, complément, période, statut, nombre d'occurrences) filtrable par statut ; pour chaque groupe, les candidats avec leur indice (« code », « numéro écrit », « rue ») et trois gestes : retenir un candidat, « aucun arrondissement », annuler (bouton du journal existant). Le compteur de l'onglet donne le nombre de groupes à traiter. Les textes sont en français.

- [ ] **Step 1 : tests qui échouent** (présence des chaînes, comme les tests statiques existants) : `test_precisions_tab_present` (« Précisions », « Aucun arrondissement », « numéro écrit », `/api/precisions/decide`).
- [ ] **Step 2 : lancer** → échec. **Step 3 : implémenter.** **Step 4 : relancer** → PASS.
- [ ] **Step 5 : vérifier à la main** : `uv run --package prosopo-gw-atelier prosopo-gw-atelier atelier/tests/fixtures/<fixture>.gw --no-browser`, ouvrir l'onglet, trancher un conflit, annuler ; noter le résultat dans le rapport.
- [ ] **Step 6 : commit** `feat(atelier): add the precisions tab`.

---

### Task 12 : documentation

**Files:**
- Modify: `atelier/README.md` (arrondissements, onglet Précisions, licence ODbL de la table parisienne), `atelier/doc/design_v1.md` (renvoi vers le spec pour les arrondissements), `docs/reflexions/points-ouverts.md` § 5 (rulings non retenus, repli éventuel du choix 11, correspondance anciens/nouveaux arrondissements non livrée : jamais univoque à l'échelle d'un arrondissement entier)

- [ ] **Step 1 : rédiger** (français, phrases courtes).
- [ ] **Step 2 : lancer toute la suite, ruff, mypy** → tout passe.
- [ ] **Step 3 : commit** `docs(atelier): describe arrondissements and occurrence precisions`.
