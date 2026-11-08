# Atelier : lieux à niveaux et communes historiques (étape 1), plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** remplacer les champs fixes d'un lieu par une chaîne de niveaux, faire des anciennes communes (fusion, association, délégation) des lieux distincts, garder tous les niveaux écrits des lieux étrangers, migrer les référentiels v1 et exporter `niveaux_lieux`.

**Architecture :** une chaîne de niveaux (`Level`) devient le modèle d'un lieu, dans les clusters comme dans le référentiel ; les cases françaises de la v1 (commune, INSEE, département…) sont une vue calculée (`french_view`). Le COG embarqué apprend l'ancien code INSEE, la nature et la date de chaque ancienne commune ; la décomposition s'en sert pour produire une `commune_historique`. Le référentiel SQLite passe en schéma 2 (table `place_levels`), avec migration journalisée et sauvegarde préalable.

**Tech Stack :** Python ≥ 3.11, workspace `uv`, SQLite (`sqlite3`), FastAPI + Pydantic, JavaScript sans framework (`web/static/app.js`), pytest, ruff, mypy strict.

**Spec :** `docs/superpowers/specs/2026-11-08-atelier-lieux-niveaux-design.md` (§ 4, 5, 9, 11, 12, 13 étape 1, 15). Les étapes 2 à 4 (arrondissements, DicoTopo, GeoNames) auront leurs propres plans.

## Global Constraints

- Dépôt **public** : fixtures synthétiques uniquement ; noms de communes et de pays réels permis, aucun nom de personne réelle ; jamais de `*.gw`/`*.ged` réel ; ne jamais lire `_local_testdata/bases/`.
- `git add` avec chemins explicites, puis `git diff --cached --name-only` ; ni `git push`, ni `--force`, ni étiquette `atelier-v*` sans accord explicite.
- `uv` exclusivement. Tests : `uv run --package prosopo-gw-atelier python -m pytest atelier`. Lint : `uv run --package prosopo-gw-atelier ruff check atelier/src atelier/tests atelier/tools` et `ruff format --check` sur les mêmes chemins. Types : `uv run --package prosopo-gw-atelier mypy --config-file atelier/pyproject.toml atelier/src/prosopo_gw_atelier`.
- Code, identifiants et messages de commit en anglais (`type(scope): message`, terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`) ; textes affichés et documentation en français.
- Tout champ écrit rempli devient un niveau ; les champs vides (`, ,`) sont ignorés ; un niveau non reconnu reste un niveau sans type. Pays normalisé comme en v1 ; pays historiques (Prusse, Bohême…) gardés tels qu'écrits.
- Un simple changement de nom (même code INSEE) n'est **pas** un lieu distinct : l'ancien nom va dans `written` du niveau commune. Seules fusion, association et délégation créent une `commune_historique`.
- Les décisions v1 sont reprises telles quelles : aucun rattachement d'écriture ne change en silence ; l'information nouvelle arrive comme **proposition**.
- Le code postal n'est pas un niveau : c'est un attribut du lieu.
- Valeurs exportées en français : origines `ecrit`, `regle`, `manuel`, `insee` (puis `paris`, `dicotopo`, `geonames`, `llm`) ; statuts `valide`, `propose`.

## Choix de ce plan (à relire)

Le spec laisse ces points au constructeur ; je les fixe ainsi :

1. **Identifiants en anglais, valeurs de données en français.** Les champs de `Level` sont en anglais (`rank`, `name`, `written`…) ; les types de niveaux sont les slugs français du spec (`commune_historique`, `localite`…), car ils sont des données exportées. Les origines internes sont en anglais (`written`, `rule`, `manual`, `insee`…) et traduites à l'export, comme en v1.
2. **Nature d'une commune historique** (`fusion`, `associee`, `deleguee`) : attribut `nature` du niveau, exporté dans une colonne `nature` de `niveaux_lieux` (le spec dit « son statut dans le niveau » sans nommer la colonne).
3. **Colonne `source`** de `niveaux_lieux` : référentiel et millésime du niveau (`COG 2026`), vide pour un niveau écrit ou manuel.
4. **Propositions de la migration stockées** dans `place_levels` (`status = 'proposed'`). Accepter = passer en `validated` ; refuser = supprimer la ligne (journalisé, donc annulable). La migration ne tourne qu'une fois, une proposition refusée ne revient pas.
5. **Cas ambigu** (nom actuel ailleurs et ancienne commune ici, ex. Sainte-Austreberthe, commune de Seine-Maritime et ancienne commune de Hesdin-la-Forêt) : l'écriture reste lue comme la commune actuelle (comportement v1), le cluster est plafonné à `medium` et porte l'autre lecture comme **alternative** ; l'écran propose « Retenir cette lecture ». Le spec cite Hesdin comme exemple ; dans le COG 2026, « Hesdin » n'est plus le nom d'aucune commune actuelle, il ne produit donc qu'une lecture (ancienne commune déléguée 62447).
6. **Hesdin et Hesdin-la-Forêt partagent le code 62447** : la clé d'une commune historique est donc `historique:<ancien code>|<nom normalisé>`, jamais le code seul.
7. **Regroupement étranger** : deux chaînes sont compatibles si l'une est une sous-suite de l'autre (noms normalisés). Les écritures d'un même groupe de nom sont réparties, de la plus longue à la plus courte, dans la première partition compatible ; s'il y a plus d'une partition, toutes passent en confiance `low`.
8. **Ordre des niveaux pour la France** : niveaux écrits non reconnus placés avant la commune s'ils sont écrits avant elle, sinon juste après le niveau reconnu qui les précède ; puis `commune_historique`, `commune`, `departement`, `ancienne_region` (si écrite), `region`, `pays`.
9. **Rangs** : les niveaux proposés sont rangés dans la chaîne avec les validés ; à l'export, les niveaux validés sont renumérotés 0, 1, 2…
10. **Lyon 69001** : `test_postal_code_of_municipal_arrondissement_maps_to_commune` reste inchangé dans cette étape (la commune reste vraie) ; l'arrondissement s'y ajoutera à l'étape 2.

## Suite rouge entre les Tasks 6 et 12

Les Tasks 6 et 7 changent `Cluster` et l'API du référentiel ; `project.py`, `web/` et `export/` ne suivent qu'aux Tasks 10 à 12. Entre-temps, chaque tâche lance seulement les tests de ses modules (commandes indiquées) et note dans son rapport le nombre de tests ailleurs en échec. À partir de la Task 12, la suite complète doit passer. Le travail se fait sur une branche (`feat/atelier-place-levels`), jamais sur `main`.

## Review Focus

- **Référentiel v1 réel ouvert par la nouvelle version** : aucune décision perdue, sauvegarde écrite **avant** toute écriture, une seule entrée `migrate` au journal ; une seconde ouverture ne refait rien. → Task 8, `test_migration_is_idempotent` et `test_backup_written_before_migration`.
- **Écriture longue ou bizarre** (`, , , ,`, une seule virgule, 12 niveaux, tirets) : pas d'exception, pas de niveau vide. → Task 5, `test_empty_and_degenerate_writings`.
- **Chaîne envoyée par l'écran invalide** (niveau sans nom, type mal formé, deux niveaux identiques, chaîne vide) : 400 en français, rien d'écrit. → Task 12, `test_validate_rejects_bad_levels`.
- **Annuler après une édition de chaîne qui a réordonné les rangs** : la chaîne d'avant revient exactement. → Task 7, `test_undo_restores_reordered_chain`.
- **Import d'un export JSON v1 dans un référentiel v2** : lieux convertis en niveaux, conflits d'écritures inchangés. → Task 9, `test_import_v1_document`.

---

## Fichiers

| Fichier | Rôle | Tâches |
|---|---|---|
| `atelier/tools/build_refdata.py` | historique avec ancien code, nature, date | 1 |
| `atelier/tests/fixtures/refdata_sources/v_mvt_commune_2026.csv` | + une ligne de changement de nom | 1 |
| `atelier/src/prosopo_gw_atelier/refdata/data/historique.csv.gz` | régénéré | 1 |
| `atelier/src/prosopo_gw_atelier/refdata/loader.py` | `Former`, `NameMatch.former` | 2 |
| `atelier/tests/fixtures/make_refdata_mini.py` + `refdata_mini/*` | Hesdin-la-Forêt, Seine-Maritime, Canada, Royaume-Uni | 2 |
| `atelier/src/prosopo_gw_atelier/places/levels.py` (nouveau) | `Level`, types, `french_view`, `chain_label`, `rule_levels` | 3, 5 |
| `atelier/src/prosopo_gw_atelier/places/model.py`, `decompose.py` | segments écrits, lecture historique | 4 |
| `atelier/src/prosopo_gw_atelier/places/cluster.py` | clés historiques, partitions étrangères, proposition en niveaux | 6 |
| `atelier/src/prosopo_gw_atelier/store/schema.sql`, `registry.py` | schéma 2, API par niveaux | 7 |
| `atelier/src/prosopo_gw_atelier/store/migrate.py` (nouveau) | migration v1 → v2 | 8 |
| `atelier/src/prosopo_gw_atelier/store/exchange.py` | JSON version 2, lecture version 1 | 9 |
| `atelier/src/prosopo_gw_atelier/project.py` | vues en niveaux, écritures historiques | 10 |
| `atelier/src/prosopo_gw_atelier/export/pivot.py`, `LISEZMOI.txt` | `lieux` modifiée, `niveaux_lieux` | 11 |
| `atelier/src/prosopo_gw_atelier/web/app.py`, `schemas.py`, `cli.py` | API par niveaux | 12 |
| `atelier/src/prosopo_gw_atelier/web/static/app.js`, `app.css` | éditeur de chaîne | 13 |
| `atelier/doc/design_v1.md`, `atelier/README.md`, `docs/reflexions/points-ouverts.md` | renvois, colonnes, points clos | 14 |

---

### Task 1 : historique du COG avec ancien code, nature et date

**Files :**
- Modify : `atelier/tools/build_refdata.py` (`Cog`, `read_communes`, `build_history`, `build`)
- Modify : `atelier/tests/fixtures/refdata_sources/v_mvt_commune_2026.csv`
- Modify : `atelier/tests/refdata/test_build_refdata.py`
- Regenerate : `atelier/src/prosopo_gw_atelier/refdata/data/historique.csv.gz`

**Interfaces :**
- Produces : `historique.csv.gz` avec l'en-tête `ancien_nom;ancien_insee;insee_actuel;nature;date_effet`, `nature ∈ {fusion, associee, deleguee, renommage}`, trié par `(ancien_nom, insee_actuel)`.
- Produces : `build_history(cog, movements, since_1943) -> list[tuple[str, str, str, str, str]]` dans cet ordre de colonnes.
- `Cog.delegated` devient `Cog.former: list[tuple[str, str, str, str]]` = `(TYPECOM, code, nom, COMPARENT)` pour chaque ligne COMA/COMD.

Règles de `nature`, dans l'ordre :
1. le couple (ancien code, nom normalisé) est une ligne COMA du COG courant → `associee` ; COMD → `deleguee` ;
2. sinon, mouvement `MOD = 10`, ou ligne de `v_commune_depuis_1943` dont le code résolu égale le code d'origine → `renommage` ;
3. sinon → `fusion`.

La date est celle du mouvement le plus récent pour ce couple (y compris pour les COMA/COMD, qui n'avaient pas de date en v1). Le reste de `build_history` (pas d'entrée pour le nom courant, commune encore actuelle sous son code ignorée) ne change pas. La colonne `MOD` est désormais utilisée.

- [ ] **Step 1 : ajouter à `v_mvt_commune_2026.csv` une ligne de renommage synthétique**

`10,1962-01-01,COM,62765,0,SAINT OMER EN ARTOIS,Saint-Omer-en-Artois,Saint-Omer-en-Artois,COM,62765,0,SAINT OMER,Saint-Omer,Saint-Omer`

- [ ] **Step 2 : écrire les tests qui échouent**

```python
def _history() -> dict[str, tuple[str, str, str, str]]:
    cog = builder.read_communes(SOURCES / "v_commune_2026.csv")
    movements = builder.read_source(SOURCES / "v_mvt_commune_2026.csv").records(
        "MOD", "DATE_EFF", "TYPECOM_AV", "COM_AV", "LIBELLE_AV", "TYPECOM_AP", "COM_AP"
    )
    since = builder.read_source(SOURCES / "v_commune_depuis_1943.csv").records(
        "TYPECOM", "COM", "LIBELLE", "DATE_FIN"
    )
    rows = builder.build_history(cog, movements, since)
    return {name: (old, current, nature, date) for name, old, current, nature, date in rows}

def test_history_associated_commune() -> None:
    assert _history()["Lomme"] == ("59355", "59350", "associee", "2000-02-27")

def test_history_delegated_commune_keeps_its_code_and_date() -> None:
    history = _history()
    assert history["Coudekerque-Village"] == ("59154", "59588", "deleguee", "2016-01-01")
    assert history["Téteghem"] == ("59588", "59588", "deleguee", "2016-01-01")

def test_history_merger_chain() -> None:
    history = _history()
    assert history["Ancienville"] == ("99001", "59512", "fusion", "1970-01-01")
    assert history["Villemilieu"] == ("99002", "59512", "fusion", "1980-01-01")

def test_history_rename_is_not_a_historical_commune() -> None:
    assert _history()["Saint-Omer-en-Artois"] == ("62765", "62765", "renommage", "1962-01-01")

def test_history_header(tmp_path: Path) -> None:
    builder.main(_args(tmp_path))
    with gzip.open(tmp_path / "historique.csv.gz", "rt", encoding="utf-8") as f:
        assert f.readline().strip() == "ancien_nom;ancien_insee;insee_actuel;nature;date_effet"
```

Adapter les tests existants qui lisent `historique.csv.gz` ou `build_history` à cinq colonnes.

- [ ] **Step 3 : vérifier l'échec** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/refdata/test_build_refdata.py -v` : les nouveaux tests échouent (tuples à 3 éléments).

- [ ] **Step 4 : implémenter** dans `build_refdata.py` selon les règles ci-dessus. Clé de déduplication inchangée `(nom normalisé, insee_actuel)` ; la ligne la plus récente fixe `ancien_insee`, `nature` et `date_effet`, sauf que le statut COMA/COMD prime sur la nature.

- [ ] **Step 5 : vérifier** — même commande, PASS.

- [ ] **Step 6 : régénérer les données embarquées** avec la commande de `atelier/README.md` § « Reconstruire les données » (sources dans `_local_testdata/refdata/`, données publiques). Contrôle :

```bash
zcat atelier/src/prosopo_gw_atelier/refdata/data/historique.csv.gz | grep -E "^(Marconne|Hesdin|Lomme|Sainte-Austreberthe);"
```
Attendu :
```
Hesdin;62447;62447;deleguee;2025-01-01
Lomme;59355;59350;associee;2000-02-27
Marconne;62549;62447;deleguee;2025-01-01
Sainte-Austreberthe;62743;62447;deleguee;2025-01-01
```
`git diff --stat` ne doit toucher que `historique.csv.gz` dans `refdata/data/` (les autres tables sont identiques octet pour octet, `mtime=0`).

- [ ] **Step 7 : commit** (le chargeur échoue jusqu'à la Task 2 : faire les Tasks 1 et 2 dans la même séance ; ne lancer que les tests du builder ici)

```bash
git add atelier/tools/build_refdata.py atelier/tests/fixtures/refdata_sources/v_mvt_commune_2026.csv atelier/tests/refdata/test_build_refdata.py atelier/src/prosopo_gw_atelier/refdata/data/historique.csv.gz
git commit -m "feat(atelier): keep former INSEE code, nature and date in COG history"
```

---

### Task 2 : le chargeur expose les anciennes communes

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/refdata/loader.py`, `refdata/__init__.py` (export de `Former`)
- Modify : `atelier/tests/fixtures/make_refdata_mini.py`, régénérer `atelier/tests/fixtures/refdata_mini/*.csv.gz`
- Modify : `atelier/tests/refdata/test_loader.py`

**Interfaces :**
- Consumes : format `historique.csv.gz` de la Task 1.
- Produces :

```python
FormerNature = Literal["fusion", "associee", "deleguee", "renommage"]

@dataclass(frozen=True)
class Former:
    name: str          # ancien nom, tel que dans le COG
    insee: str         # ancien code INSEE
    current: str       # code INSEE de la commune actuelle
    nature: FormerNature
    date: str          # date d'effet ISO, "" si inconnue

@dataclass(frozen=True)
class NameMatch:
    commune: Commune
    former_name: str | None   # inchangé (v1)
    former: Former | None = None   # renseigné quand former_name l'est

def RefData.former_communes(self, insee: str) -> list[Former]  # anciennes communes rattachées à une commune actuelle, triées par nom
```

- [ ] **Step 1 : compléter la fixture `make_refdata_mini.py`** (données publiques du COG 2026) :
  - `communes` : `62447;Hesdin-la-Forêt;62;32`, `76566;Sainte-Austreberthe;76;28` ;
  - `historique` (nouvel en-tête) : `Fort-Mardyck;59248;59183;associee;2010-12-09`, `Hellemmes-Lille;59298;59350;associee;1977-04-24`, `Lomme;59355;59350;associee;2000-02-27`, `Hesdin;62447;62447;deleguee;2025-01-01`, `Marconne;62549;62447;deleguee;2025-01-01`, `Sainte-Austreberthe;62743;62447;deleguee;2025-01-01`, `Saint-Omer-en-Artois;62765;62765;renommage;1962-01-01` (cette dernière est synthétique : le dire dans la docstring) ;
  - `departements` : `76;Seine-Maritime;28` ; `regions` : `28;Normandie;0` ;
  - `pays` : `Canada;Canada`, `Royaume-Uni;Royaume-Uni de Grande-Bretagne et d'Irlande du Nord` ;
  - `codes_postaux` : `62140;62447`.
  Puis lancer le script (commande de sa docstring).

- [ ] **Step 2 : écrire les tests qui échouent** (remplacer `test_merged_commune`)

```python
def test_merged_commune(ref: RefData) -> None:
    matches = ref.communes_by_name("Lomme")
    assert len(matches) == 1
    assert matches[0].former == Former("Lomme", "59355", "59350", "associee", "2000-02-27")
    assert matches[0].former_name == "Lomme"

def test_delegated_commune_sharing_the_new_code(ref: RefData) -> None:
    [match] = ref.communes_by_name("Hesdin")
    assert match.commune.insee == "62447"
    assert match.former == Former("Hesdin", "62447", "62447", "deleguee", "2025-01-01")

def test_current_name_and_former_name_elsewhere(ref: RefData) -> None:
    matches = ref.communes_by_name("Sainte-Austreberthe")
    readings = sorted((m.commune.insee, m.former is not None) for m in matches)
    assert readings == [("62447", True), ("76566", False)]

def test_rename(ref: RefData) -> None:
    [match] = ref.communes_by_name("Saint-Omer-en-Artois")
    assert match.former is not None and match.former.nature == "renommage"

def test_former_communes(ref: RefData) -> None:
    assert [f.name for f in ref.former_communes("62447")] == ["Hesdin", "Marconne", "Sainte-Austreberthe"]
    assert ref.former_communes("59512") == []
```

- [ ] **Step 3 : vérifier l'échec** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/refdata -v`.

- [ ] **Step 4 : implémenter** la lecture des cinq colonnes, `Former`, `NameMatch.former`, `former_communes`. `test_embedded_reference_data` doit passer sur les données régénérées.

- [ ] **Step 5 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier` : tout passe sauf, éventuellement, des tests de `places/` qui comptent les communes de la fixture ; les corriger seulement si le nombre change, pas le comportement.

- [ ] **Step 6 : commit**

```bash
git add atelier/src/prosopo_gw_atelier/refdata/loader.py atelier/src/prosopo_gw_atelier/refdata/__init__.py atelier/tests/fixtures/make_refdata_mini.py atelier/tests/fixtures/refdata_mini atelier/tests/refdata/test_loader.py
git commit -m "feat(atelier): expose former communes with code, nature and date"
```

---

### Task 3 : le modèle de niveaux

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/places/levels.py`
- Create : `atelier/tests/places/test_levels.py`

**Interfaces :**
- Produces :

```python
LevelOrigin = Literal["written", "rule", "manual", "insee", "paris", "dicotopo", "geonames", "llm"]
LevelStatus = Literal["validated", "proposed"]
HistoricalNature = Literal["fusion", "associee", "deleguee"]

FRENCH_TYPES: tuple[str, ...] = ("lieu_dit", "quartier", "arrondissement", "commune_historique",
    "commune", "departement", "region", "ancienne_region", "pays")
FOREIGN_TYPES: tuple[str, ...] = ("localite", "comte", "province", "etat",
    "nation_constitutive", "oblast", "canton", "district")
TYPE_LABELS: dict[str, str]   # libellé français de chaque type ci-dessus ("commune_historique": "Commune historique", "nation_constitutive": "Nation constitutive"…)
TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")   # liste ouverte : tout slug conforme est accepté

@dataclass(frozen=True)
class Level:
    rank: int
    name: str
    written: str | None = None
    type: str | None = None
    identifier: str | None = None
    source: str | None = None
    start: str | None = None
    end: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    nature: HistoricalNature | None = None
    origin: LevelOrigin = "rule"
    status: LevelStatus = "validated"

ViewField = Literal["commune", "insee_code", "postal_code", "department", "region",
    "country", "historical_commune", "historical_insee"]

def check_chain(levels: Sequence[Level]) -> None          # ValueError (message en français) si : chaîne vide, nom vide, type hors TYPE_PATTERN, rangs non 0..n-1, latitude hors [-90, 90] ou longitude hors [-180, 180]
def renumber(levels: Sequence[Level]) -> tuple[Level, ...]  # rangs 0..n-1 dans l'ordre donné
def validated(levels: Sequence[Level]) -> tuple[Level, ...]  # niveaux validés, renumérotés
def french_view(levels: Sequence[Level], postal_code: str | None) -> dict[ViewField, str]
def view_origins(levels: Sequence[Level]) -> dict[ViewField, LevelOrigin]
def chain_label(levels: Sequence[Level]) -> str           # noms des niveaux validés joints par ", "
```

`french_view` lit seulement les niveaux validés : `commune` et `insee_code` = nom et identifiant du premier niveau `commune` ; `historical_commune`, `historical_insee` = ceux du niveau `commune_historique` ; `department` = identifiant (code) du niveau `departement`, sinon son nom ; `region` = nom du niveau `region`, sinon `ancienne_region` ; `country` = nom du niveau `pays` ; `postal_code` = l'argument. Une clé sans valeur est absente.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
MARCONNE = (
    Level(0, "Marconne", type="commune_historique", identifier="62549", end="2025-01-01", nature="deleguee", origin="insee", source="COG 2026"),
    Level(1, "Hesdin-la-Forêt", type="commune", identifier="62447", origin="insee", source="COG 2026"),
    Level(2, "Pas-de-Calais", type="departement", identifier="62", origin="insee", source="COG 2026"),
    Level(3, "Hauts-de-France", type="region", origin="insee", source="COG 2026"),
    Level(4, "France", type="pays", origin="written"),
)

def test_french_view_of_historical_commune() -> None:
    assert french_view(MARCONNE, "62140") == {
        "commune": "Hesdin-la-Forêt", "insee_code": "62447", "postal_code": "62140",
        "department": "62", "region": "Hauts-de-France", "country": "France",
        "historical_commune": "Marconne", "historical_insee": "62549",
    }

def test_french_view_ignores_proposals() -> None:
    chain = (Level(0, "Lille", type="commune", identifier="59350"),
             Level(1, "Lomme", type="commune_historique", status="proposed"))
    assert "historical_commune" not in french_view(chain, None)

def test_view_origins() -> None:
    assert view_origins(MARCONNE)["country"] == "written"
    assert view_origins(MARCONNE)["commune"] == "insee"

def test_chain_label() -> None:
    assert chain_label(MARCONNE) == "Marconne, Hesdin-la-Forêt, Pas-de-Calais, Hauts-de-France, France"

def test_validated_renumbers() -> None:
    chain = (Level(0, "A", status="proposed"), Level(1, "B"), Level(2, "C"))
    assert [(l.rank, l.name) for l in validated(chain)] == [(0, "B"), (1, "C")]

@pytest.mark.parametrize("chain, message", [
    ((), "au moins un niveau"),
    ((Level(0, " "),), "nom"),
    ((Level(0, "A", type="Comté"),), "type"),
    ((Level(1, "A"),), "rang"),
    ((Level(0, "A", latitude=91.0),), "latitude"),
])
def test_check_chain_rejects(chain: tuple[Level, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_chain(chain)

def test_every_listed_type_has_a_label() -> None:
    assert set(TYPE_LABELS) == set(FRENCH_TYPES) | set(FOREIGN_TYPES)
    assert all(TYPE_PATTERN.match(t) for t in TYPE_LABELS)
```

- [ ] **Step 2 : vérifier l'échec** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/places/test_levels.py -v` : ImportError.
- [ ] **Step 3 : implémenter** `places/levels.py` (pur, sans dépendance au COG).
- [ ] **Step 4 : vérifier** — PASS ; mypy sur le module.
- [ ] **Step 5 : commit** `git add atelier/src/prosopo_gw_atelier/places/levels.py atelier/tests/places/test_levels.py` ; `feat(atelier): add the place level model`.

---

### Task 4 : la décomposition garde chaque segment et lit les communes historiques

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/places/model.py`, `places/decompose.py`
- Modify : `atelier/tests/places/test_decompose.py`

**Interfaces :**
- Consumes : `Former`, `NameMatch.former` (Task 2).
- Produces :

```python
@dataclass(frozen=True)
class Segment:
    text: str                    # segment écrit, nettoyé comme par segments()
    element: Element | None      # l'élément reconnu dans ce segment, None si aucun

@dataclass(frozen=True)
class Decomposition:
    writing: str
    elements: tuple[Element, ...]
    insee: str | None
    candidates: tuple[str, ...]
    ambiguous: bool
    segments: tuple[Segment, ...] = ()        # tous les segments non vides, codes compris, dans l'ordre écrit
    historical: Former | None = None          # l'écriture désigne cette ancienne commune (fusion/associée/déléguée)
    alternative: Former | None = None         # autre lecture possible : ancienne commune homonyme d'une commune actuelle retenue
```

Règles :
- `historical` est renseigné quand le segment de nom n'a reconnu qu'un ancien nom, que la commune est résolue (`insee` non nul) et que l'ancienne commune correspondant à `insee` a une nature autre que `renommage`. Un renommage garde l'élément `former_name` (v1) et `historical = None`.
- `alternative` est renseigné quand le segment de nom a reconnu une commune actuelle **et** une ancienne commune (non renommée) dont la commune actuelle est retenue par les autres indices, ou que rien ne les départage ; s'il y a plusieurs anciennes communes possibles, la première par code.
- Avec « Sainte-Austreberthe, Pas-de-Calais », le département retient 62447 : la lecture devient `historical` (ancienne commune déléguée), `alternative = None`.
- `elements`, `insee`, `candidates` et `ambiguous` gardent leur sens v1.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
def test_foreign_levels_are_all_kept(ref: RefData) -> None:
    d = decompose("Winnipeg, , , Manitoba, Canada", ref)
    assert [s.text for s in d.segments] == ["Winnipeg", "Manitoba", "Canada"]
    assert [s.element.kind if s.element else None for s in d.segments] == [None, None, "country"]

def test_four_written_levels(ref: RefData) -> None:
    d = decompose("Storrington, , East Sussex, England, Royaume-Uni", ref)
    assert [s.text for s in d.segments] == ["Storrington", "East Sussex", "England", "Royaume-Uni"]

def test_delegated_commune_is_historical(ref: RefData) -> None:
    d = decompose("Marconne, Pas-de-Calais", ref)
    assert d.insee == "62447"
    assert d.historical == Former("Marconne", "62549", "62447", "deleguee", "2025-01-01")

def test_rename_is_not_historical(ref: RefData) -> None:
    d = decompose("Saint-Omer-en-Artois", ref)
    assert d.insee == "62765" and d.historical is None
    assert [e.kind for e in d.elements] == ["former_name"]

def test_current_name_with_former_alternative(ref: RefData) -> None:
    d = decompose("Sainte-Austreberthe, Seine-Maritime", ref)
    assert d.insee == "76566" and d.historical is None
    assert d.alternative is not None and d.alternative.insee == "62743"

def test_department_picks_the_former_reading(ref: RefData) -> None:
    d = decompose("Sainte-Austreberthe, Pas-de-Calais", ref)
    assert d.insee == "62447"
    assert d.historical is not None and d.historical.insee == "62743"
    assert d.alternative is None

def test_codes_are_segments_too(ref: RefData) -> None:
    d = decompose("Roubaix 59100", ref)
    assert [(s.text, s.element.kind if s.element else None) for s in d.segments] == [("Roubaix", "commune"), ("59100", "postal_code")]
```

- [ ] **Step 2 : vérifier l'échec** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/places/test_decompose.py -v`.
- [ ] **Step 3 : implémenter.** `_State` garde l'index de segment de chaque élément (déjà le cas) : construire `segments` à la fin à partir de `segments(writing)` et des éléments indexés. Les tests v1 de `test_decompose.py` doivent continuer de passer sans modification.
- [ ] **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/places -v` PASS.
- [ ] **Step 5 : commit** `feat(atelier): keep every written segment and read historical communes` (fichiers listés ci-dessus).

---

### Task 5 : la chaîne de niveaux proposée par les règles

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/places/levels.py`
- Modify : `atelier/tests/places/test_levels.py`

**Interfaces :**
- Consumes : `Decomposition.segments`, `historical`, `alternative` (Task 4) ; `RefData` (`commune_by_insee`, `department`, `region_name`, `region`, `country`, `cog_vintage`).
- Produces :

```python
def rule_levels(decomposition: Decomposition, ref: RefData) -> tuple[Level, ...]
def alternative_levels(decomposition: Decomposition, ref: RefData) -> tuple[Level, ...] | None   # chaîne de la lecture `alternative`, None sans alternative
def written_postal_code(decomposition: Decomposition) -> str | None
```

Règles de `rule_levels` (statut `validated`, pour une proposition de cluster) :
- **Commune résolue** (`insee` non nul) : `commune_historique` si `historical` (nom = `Former.name`, `identifier` = ancien code, `end` = date si non vide, `nature`, origine `insee`), puis `commune` (nom officiel, `identifier` = INSEE, `written` = nom écrit s'il diffère, origine `insee`), `departement` (nom du département, `identifier` = code, origine `insee`), `ancienne_region` si une région d'avant 2016 est écrite (origine `written`), `region` (origine `insee`), `pays` « France » (origine `written` si écrit, sinon `insee`). `source = f"COG {ref.cog_vintage}"` pour les niveaux d'origine `insee`.
- **Segments non reconnus** (texte, pas un code) d'une commune résolue : placés selon le choix 8 de ce plan, origine `written`, sans type.
- **Commune non résolue** : un niveau par segment non code, dans l'ordre écrit ; type `pays` (nom normalisé par `ref.country`) ou `departement`/`region` quand le segment est reconnu, sinon sans type ; origine `written` (ou `rule` pour un nom normalisé différent de l'écrit, `written` gardant l'écrit).
- Les codes INSEE et postaux ne sont jamais des niveaux ; `written_postal_code` rend le premier élément `postal_code`.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
def _names(chain: tuple[Level, ...]) -> list[tuple[str, str | None]]:
    return [(l.name, l.type) for l in chain]

def test_winnipeg_keeps_manitoba(ref: RefData) -> None:
    chain = rule_levels(decompose("Winnipeg, , , Manitoba, Canada", ref), ref)
    assert _names(chain) == [("Winnipeg", None), ("Manitoba", None), ("Canada", "pays")]
    assert [l.rank for l in chain] == [0, 1, 2]

def test_storrington_keeps_four_levels(ref: RefData) -> None:
    chain = rule_levels(decompose("Storrington, , East Sussex, England, Royaume-Uni", ref), ref)
    assert [l.name for l in chain] == ["Storrington", "East Sussex", "England", "Royaume-Uni"]
    assert all(l.origin == "written" for l in chain)

def test_marconne_chain(ref: RefData) -> None:
    chain = rule_levels(decompose("Marconne, Pas-de-Calais", ref), ref)
    assert _names(chain) == [
        ("Marconne", "commune_historique"), ("Hesdin-la-Forêt", "commune"),
        ("Pas-de-Calais", "departement"), ("Hauts-de-France", "region"), ("France", "pays")]
    assert chain[0].identifier == "62549" and chain[0].end == "2025-01-01" and chain[0].nature == "deleguee"
    assert chain[1].source == "COG 2026"

def test_rename_kept_as_written_name(ref: RefData) -> None:
    chain = rule_levels(decompose("Saint-Omer-en-Artois", ref), ref)
    assert chain[0].name == "Saint-Omer" and chain[0].written == "Saint-Omer-en-Artois"
    assert chain[0].type == "commune"

def test_unrecognised_segment_before_commune(ref: RefData) -> None:
    chain = rule_levels(decompose("La Motte, Roubaix, Nord", ref), ref)
    assert _names(chain)[:2] == [("La Motte", None), ("Roubaix", "commune")]

def test_old_region_is_kept(ref: RefData) -> None:
    chain = rule_levels(decompose("Roubaix, Nord-Pas-de-Calais", ref), ref)
    assert ("Nord-Pas-de-Calais", "ancienne_region") in _names(chain)
    assert ("Hauts-de-France", "region") in _names(chain)

def test_historical_country_stays_as_written(ref: RefData) -> None:
    chain = rule_levels(decompose("Königsberg, Prusse", ref), ref)
    assert _names(chain) == [("Königsberg", None), ("Prusse", None)]

def test_alternative_levels(ref: RefData) -> None:
    alt = alternative_levels(decompose("Sainte-Austreberthe", ref), ref)
    assert alt is not None and alt[0].type == "commune_historique" and alt[1].name == "Hesdin-la-Forêt"

@pytest.mark.parametrize("writing", [", , , ,", ",", "-", " ; ( ) ", "A, B, C, D, E, F, G, H, I, J, K, L"])
def test_empty_and_degenerate_writings(ref: RefData, writing: str) -> None:
    chain = rule_levels(decompose(writing, ref), ref)
    assert all(l.name.strip() for l in chain)
    assert [l.rank for l in chain] == list(range(len(chain)))
```

- [ ] **Step 2 : vérifier l'échec**, **Step 3 : implémenter**, **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/places -v`.
- [ ] **Step 5 : commit** `feat(atelier): propose a level chain from a decomposed writing`.

---

### Task 6 : clusters à niveaux, communes historiques distinctes, partitions étrangères

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/places/cluster.py` (docstring comprise)
- Modify : `atelier/tests/places/test_cluster.py`

**Interfaces :**
- Consumes : `rule_levels`, `alternative_levels`, `written_postal_code` (Task 5).
- Produces :

```python
@dataclass(frozen=True)
class KnownPlace:
    place_id: str
    insee: str | None             # INSEE du niveau commune, None si le premier niveau validé est une commune_historique
    name_key: str                 # name_key du premier niveau validé
    department: str | None = None
    historical: str | None = None # f"{ancien code}|{name_key}" si le premier niveau validé est une commune_historique

@dataclass
class Cluster:
    id: str
    writings: list[str]
    levels: tuple[Level, ...]                 # remplace `proposal`
    postal_code: str | None
    confidence: Confidence
    anchor_place_id: str | None = None
    alternatives: tuple[tuple[Level, ...], ...] = ()
```

Règles (à reporter dans la docstring du module) :
- **Clés** : `historique:<ancien code>|<name_key>` pour une écriture dont `historical` est renseigné ; sinon `insee:` et `name:` comme en v1.
- **Proposition** : la chaîne `rule_levels` la plus longue du cluster (égalité : la plus fréquente, puis la plus petite écriture) ; pour un cluster `insee:`, la chaîne de la commune actuelle reconstruite depuis le COG (comme v1) en gardant les niveaux écrits non reconnus des membres. `postal_code` : majoritaire parmi `written_postal_code` (égalité : la plus petite valeur).
- **Ancre** : un cluster `historique:` s'ancre sur le lieu dont `historical` est égal ; un cluster `insee:` ne s'ancre jamais sur un lieu qui a une `historical`. Règles v1 sinon.
- **Alternatives** : les `alternative_levels` distinctes des membres ; s'il y en a, confiance plafonnée à `medium`.
- **Partitions** des clusters sans INSEE (choix 7) : ids `name:<clé>` pour la première, `name:<clé>~2`, `~3`… pour les suivantes, dans l'ordre de création ; toutes en `low` dès qu'il y en a deux.

- [ ] **Step 1 : écrire les tests qui échouent** (adapter les tests v1 qui lisent `proposal` à `french_view(cluster.levels, cluster.postal_code)`)

```python
def test_marconne_hesdin_and_hesdin_la_foret_are_three_clusters(ref: RefData) -> None:
    clusters = _clusters(["Marconne", "Hesdin, Pas-de-Calais", "Hesdin-la-Forêt"], ref)
    assert sorted(c.id for c in clusters) == ["historique:62447|hesdin", "historique:62549|marconne", "insee:62447"]
    marconne = _by_id(clusters, "historique:62549|marconne")
    assert [l.name for l in marconne.levels][:2] == ["Marconne", "Hesdin-la-Forêt"]

def test_lomme_is_not_merged_into_lille(ref: RefData) -> None:
    ids = {c.id for c in _clusters(["Lomme", "Lille"], ref)}
    assert ids == {"historique:59355|lomme", "insee:59350"}

def test_foreign_writings_without_contradiction_merge(ref: RefData) -> None:
    [cluster] = _clusters(["Storrington, Royaume-Uni", "Storrington, , East Sussex, England, Royaume-Uni"], ref)
    assert [l.name for l in cluster.levels] == ["Storrington", "East Sussex", "England", "Royaume-Uni"]

def test_contradicting_levels_split_with_low_confidence(ref: RefData) -> None:
    clusters = _clusters(["Storrington, East Sussex", "Storrington, West Sussex"], ref)
    assert len(clusters) == 2
    assert {c.confidence for c in clusters} == {"low"}
    assert sorted(c.id for c in clusters) == ["name:storrington", "name:storrington~2"]

def test_ambiguous_former_name_is_medium_with_alternative(ref: RefData) -> None:
    [cluster] = _clusters(["Sainte-Austreberthe, Seine-Maritime"], ref)
    assert cluster.id == "insee:76566" and cluster.confidence == "medium"
    assert cluster.alternatives[0][0].name == "Sainte-Austreberthe" and cluster.alternatives[0][1].name == "Hesdin-la-Forêt"

def test_historical_anchor(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", None, "marconne", "62", "62549|marconne"),
             "p2": KnownPlace("p2", "62447", "hesdin la foret", "62")}
    clusters = build_clusters({w: decompose(w, ref) for w in ["Marconne", "Hesdin-la-Forêt"]}, ref, known)
    assert {c.id: c.anchor_place_id for c in clusters} == {"historique:62549|marconne": "p1", "insee:62447": "p2"}

def test_postal_code_proposal(ref: RefData) -> None:
    [cluster] = _clusters(["Roubaix 59100", "Roubaix"], ref)
    assert cluster.postal_code == "59100"
```

(`_clusters(writings, ref)` : helper local `build_clusters({w: decompose(w, ref) for w in writings}, ref, {})` ; `_by_id` idem.)

- [ ] **Step 2 : vérifier l'échec**, **Step 3 : implémenter**, **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/places -v` PASS (le reste de la suite casse jusqu'à la Task 10 : c'est attendu, noter le décompte dans le rapport).
- [ ] **Step 5 : commit** `feat(atelier): cluster historical communes apart and keep foreign levels`.

---

### Task 7 : référentiel en schéma 2 (niveaux)

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/store/schema.sql` (schéma 2 pour une base neuve), `store/registry.py`
- Modify : `atelier/tests/store/test_registry.py`

**Interfaces :**
- Consumes : `Level`, `check_chain`, `renumber`, `french_view` (Task 3) ; `KnownPlace` (Task 6).
- Produces :

```sql
-- en plus de places, writings, journal (inchangées, sauf l'action 'migrate' admise par journal)
CREATE TABLE IF NOT EXISTS place_levels (
    place_id TEXT NOT NULL REFERENCES places (place_id),
    rank INTEGER NOT NULL CHECK (rank >= 0),
    name TEXT NOT NULL, written TEXT, type TEXT, identifier TEXT, source TEXT,
    start TEXT, "end" TEXT, latitude REAL, longitude REAL,
    nature TEXT CHECK (nature IN ('fusion', 'associee', 'deleguee')),
    origin TEXT NOT NULL CHECK (origin IN ('written', 'rule', 'manual', 'insee', 'paris', 'dicotopo', 'geonames', 'llm')),
    status TEXT NOT NULL CHECK (status IN ('validated', 'proposed')),
    PRIMARY KEY (place_id, rank)
);
CREATE TABLE IF NOT EXISTS place_attributes (
    place_id TEXT NOT NULL REFERENCES places (place_id),
    name TEXT NOT NULL CHECK (name IN ('postal_code')),
    value TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('written', 'rule', 'manual', 'insee')),
    PRIMARY KEY (place_id, name)
);
PRAGMA user_version = 2;
```
`place_fields` n'existe plus dans le schéma 2.

```python
SCHEMA_VERSION = 2

@dataclass(frozen=True)
class Place:
    place_id: str
    levels: tuple[Level, ...]             # validés et proposés, par rang
    postal_code: str | None = None
    postal_origin: LevelOrigin | None = None
    @property
    def fields(self) -> dict[ViewField, str]: ...   # french_view(levels, postal_code)

def PlaceRegistry.__init__(self, path: Path, ref: RefData | None = None) -> None   # ref sert à la migration (Task 8)
def PlaceRegistry.validate(self, writings: Sequence[str], levels: Sequence[Level],
        postal_code: str | None, postal_origin: LevelOrigin | None,
        project: str, place_id: str | None = None) -> Validation
def PlaceRegistry.set_levels(self, place_id: str, levels: Sequence[Level],
        postal_code: str | None, postal_origin: LevelOrigin | None, project: str) -> int | None   # remplace la chaîne entière (action 'correct')
def PlaceRegistry.accept_proposal(self, place_id: str, rank: int, project: str) -> int | None   # status -> validated (action 'correct')
def PlaceRegistry.refuse_proposal(self, place_id: str, rank: int, project: str) -> int | None   # supprime le niveau proposé et renumérote (action 'correct')
def PlaceRegistry.known_places(self) -> list[KnownPlace]   # selon les niveaux validés
```

`validate` et `set_levels` appellent `check_chain` (ValueError) ; tous les changements passent par `RowChange` (`place_levels` : clé `(place_id, rank)` ; `place_attributes` : clé `(place_id, name)`), donc `undo` et l'import marchent sans code nouveau. `_TABLES` et la docstring de `RowChange` sont mis à jour ; `correct(place_id, field, value, project)` disparaît.

- [ ] **Step 1 : écrire les tests qui échouent** (réécrire les tests v1 qui passaient `fields`/`origins` : mêmes scénarios, avec une chaîne)

```python
LILLE = (Level(0, "Lille", type="commune", identifier="59350", origin="insee"),
         Level(1, "Nord", type="departement", identifier="59", origin="insee"),
         Level(2, "France", type="pays", origin="written"))

def test_validate_stores_levels(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, "59000", "written", "p1")
    place = registry.place(v.place_id)
    assert place.levels == LILLE and place.postal_code == "59000"
    assert place.fields["insee_code"] == "59350"

def test_set_levels_and_undo_restores_reordered_chain(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, None, None, "p1")
    reordered = renumber((Level(0, "Fives", origin="manual"), *LILLE))
    entry = registry.set_levels(v.place_id, reordered, None, None, "p1")
    assert [l.name for l in registry.place(v.place_id).levels] == ["Fives", "Lille", "Nord", "France"]
    registry.undo(entry)
    assert registry.place(v.place_id).levels == LILLE

def test_accept_and_refuse_proposal(registry: PlaceRegistry) -> None:
    chain = (*LILLE, Level(3, "Flandre", status="proposed", origin="written"))
    v = registry.validate(["LILLE"], chain, None, None, "p1")
    registry.accept_proposal(v.place_id, 3, "p1")
    assert registry.place(v.place_id).levels[3].status == "validated"
    v2 = registry.validate(["LOMME"], renumber((Level(0, "Lomme", status="proposed"), *LILLE)), None, None, "p1")
    registry.refuse_proposal(v2.place_id, 0, "p1")
    assert [l.rank for l in registry.place(v2.place_id).levels] == [0, 1, 2]

def test_validate_rejects_invalid_chain(registry: PlaceRegistry) -> None:
    with pytest.raises(ValueError):
        registry.validate(["X"], (Level(0, ""),), None, None, "p1")
    assert registry.decisions(["X"]) == {}

def test_known_places_historical(registry: PlaceRegistry) -> None:
    chain = (Level(0, "Marconne", type="commune_historique", identifier="62549", nature="deleguee", origin="insee"),
             Level(1, "Hesdin-la-Forêt", type="commune", identifier="62447", origin="insee"))
    v = registry.validate(["Marconne"], chain, None, None, "p1")
    [known] = registry.known_places()
    assert known == KnownPlace(v.place_id, None, "marconne", None, "62549|marconne")

def test_new_registry_is_version_2(tmp_path: Path) -> None:
    PlaceRegistry(tmp_path / "r.sqlite").close()
    assert sqlite3.connect(tmp_path / "r.sqlite").execute("PRAGMA user_version").fetchone()[0] == 2
```

- [ ] **Step 2 : vérifier l'échec** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/store/test_registry.py -v`.
- [ ] **Step 3 : implémenter** (ouverture d'un fichier en version 1 : lever `SchemaVersionError` « migration requise » tant que la Task 8 n'est pas faite).
- [ ] **Step 4 : vérifier** — PASS pour `test_registry.py`.
- [ ] **Step 5 : commit** `feat(atelier): store places as level chains (registry schema 2)`.

---

### Task 8 : migration d'un référentiel v1

**Files :**
- Create : `atelier/src/prosopo_gw_atelier/store/migrate.py`
- Create : `atelier/tests/fixtures/registry_v1.sql` (copie du `schema.sql` v1 actuel, commit 20a2945, pour fabriquer des bases v1 dans les tests)
- Modify : `atelier/src/prosopo_gw_atelier/store/registry.py` (appel de la migration à l'ouverture)
- Create : `atelier/tests/store/test_migrate.py`

**Interfaces :**
- Consumes : `rule_levels`, `decompose` (Tasks 4-5), `RefData`, schéma 2 (Task 7).
- Produces :

```python
def backup_path(path: Path, at: datetime) -> Path   # path.with_name(f"{path.stem}.v1-{at:%Y%m%dT%H%M%S}.sqlite")
def migrate_v1(conn: sqlite3.Connection, path: Path, ref: RefData) -> None
```

Comportement :
1. **Sauvegarde d'abord** : `sqlite3.Connection.backup` vers `backup_path(...)`, avant toute écriture ; si la sauvegarde échoue, rien n'est modifié et l'erreur remonte.
2. Puis une seule transaction `BEGIN IMMEDIATE` : création de `place_levels` et `place_attributes`, reconstruction de `journal` avec l'action `migrate` admise, conversion de chaque lieu, suppression de `place_fields`, `PRAGMA user_version = 2`.
3. **Conversion d'un lieu v1** : `commune` (+ `insee_code` en identifiant), `department`, `region`, `country` deviennent des niveaux validés, dans cet ordre, avec l'origine v1 traduite (`rule`→`rule`, `manual`→`manual`, `reference`→`insee`, `llm`→`llm`) ; `postal_code` va dans `place_attributes`.
4. **Propositions** (statut `proposed`, origine `insee` ou `written`) :
   - `former_name` rempli et reconnu par `ref.communes_by_name` comme ancienne commune non renommée de la commune du lieu → niveau `commune_historique` proposé au rang 0 (ancien code, nature, date) ; reconnu comme renommage → `written` du niveau commune, sans proposition ; non reconnu → niveau proposé sans type au rang 0 ;
   - pour chaque écriture validée vers ce lieu, `rule_levels(decompose(écriture, ref), ref)` : tout niveau d'origine `written` dont le nom normalisé manque à la chaîne du lieu → niveau proposé, inséré à sa place relative (choix 8), une seule fois par nom.
5. **Décisions** (`writings`) : inchangées, ligne pour ligne.
6. **Journal** : une entrée `migrate`, `project = NULL`, payload `{"from": 1, "to": 2, "backup": "<nom du fichier>", "places": <n>, "proposals": <n>}`, sans `RowChange` (non annulable : `undo` d'une entrée `migrate` lève `ValueError` « la migration ne s'annule pas ; la sauvegarde est <fichier> »).
7. Ouvrir un fichier v1 sans `ref` → `SchemaVersionError` qui le dit.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
def _v1_registry(path: Path) -> None:
    """Base v1 synthétique : Lille avec ancien nom Lomme (2 écritures), Winnipeg sans Manitoba, une écriture rejetée."""
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / "registry_v1.sql").read_text("utf-8"))
    conn.executescript("""
      INSERT INTO places VALUES ('p-lille', '2026-11-01T00:00:00+00:00'), ('p-winnipeg', '2026-11-01T00:00:00+00:00');
      INSERT INTO place_fields VALUES
        ('p-lille','commune','Lille','reference'), ('p-lille','insee_code','59350','reference'),
        ('p-lille','department','59','reference'), ('p-lille','region','Hauts-de-France','reference'),
        ('p-lille','country','France','rule'), ('p-lille','former_name','Lomme','rule'),
        ('p-lille','postal_code','59000','rule'),
        ('p-winnipeg','commune','Winnipeg','rule'), ('p-winnipeg','country','Canada','rule');
      INSERT INTO writings VALUES
        ('Lille', 'p-lille', 'validated', 'p1', '2026-11-01T00:00:00+00:00'),
        ('Lomme', 'p-lille', 'validated', 'p1', '2026-11-01T00:00:00+00:00'),
        ('Winnipeg, , , Manitoba, Canada', 'p-winnipeg', 'validated', 'p1', '2026-11-01T00:00:00+00:00'),
        ('en mer', NULL, 'rejected', 'p1', '2026-11-01T00:00:00+00:00');
    """)
    conn.close()

def test_decisions_survive(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        d = registry.decisions(["Lille", "Lomme", "Winnipeg, , , Manitoba, Canada", "en mer"])
        assert {w: (x.status, x.place_id) for w, x in d.items()} == {
            "Lille": ("validated", "p-lille"), "Lomme": ("validated", "p-lille"),
            "Winnipeg, , , Manitoba, Canada": ("validated", "p-winnipeg"), "en mer": ("rejected", None)}

def test_lille_levels_and_lomme_proposal(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        place = registry.place("p-lille")
    assert [(l.name, l.type, l.status) for l in place.levels] == [
        ("Lomme", "commune_historique", "proposed"), ("Lille", "commune", "validated"),
        ("Nord", "departement", "validated"), ("Hauts-de-France", "region", "validated"),
        ("France", "pays", "validated")]
    assert place.levels[0].identifier == "59355" and place.levels[1].origin == "insee"
    assert place.postal_code == "59000"

def test_winnipeg_gets_manitoba_as_proposal(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        place = registry.place("p-winnipeg")
    assert [(l.name, l.status) for l in place.levels] == [
        ("Winnipeg", "validated"), ("Manitoba", "proposed"), ("Canada", "validated")]

def test_backup_written_before_migration(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    PlaceRegistry(tmp_path / "r.sqlite", ref).close()
    [backup] = tmp_path.glob("r.v1-*.sqlite")
    conn = sqlite3.connect(backup)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM place_fields").fetchone()[0] == 9

def test_migration_is_journaled_once_and_idempotent(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    PlaceRegistry(tmp_path / "r.sqlite", ref).close()
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        entries = [e for e in registry.journal() if e.action == "migrate"]
        assert len(entries) == 1 and entries[0].payload["places"] == 2
        with pytest.raises(ValueError, match="sauvegarde"):
            registry.undo(entries[0].entry_id)
    assert len(list(tmp_path.glob("r.v1-*.sqlite"))) == 1

def test_v1_without_reference_data(tmp_path: Path) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with pytest.raises(SchemaVersionError, match="migr"):
        PlaceRegistry(tmp_path / "r.sqlite")
```

- [ ] **Step 2 : vérifier l'échec** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/store/test_migrate.py -v`.
- [ ] **Step 3 : implémenter** `migrate.py` et l'appel depuis `PlaceRegistry.__init__` quand `user_version == 1`.
- [ ] **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/store -v`.
- [ ] **Step 5 : commit** `feat(atelier): migrate v1 registries to level chains with a backup`.

---

### Task 9 : export JSON du référentiel en version 2

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/store/exchange.py` (docstring comprise)
- Modify : `atelier/tests/store/test_exchange.py`

**Interfaces :**
- Consumes : `Place`, `set_levels`, conversion v1 de `migrate.py` (exposer `levels_from_v1(fields: Mapping[str, str], origins: Mapping[str, str], ref: RefData | None) -> tuple[tuple[Level, ...], str | None, LevelOrigin | None]` dans `migrate.py` et la réutiliser ici ; avec `ref=None`, `former_name` devient un niveau proposé sans type).
- Produces : `VERSION = 2` ; format d'un lieu :

```json
{"place_id": "<uuid>",
 "postal_code": {"value": "59000", "origin": "written"},
 "levels": [{"rank": 0, "name": "Lille", "written": null, "type": "commune", "identifier": "59350",
             "source": "COG 2026", "start": null, "end": null, "latitude": null, "longitude": null,
             "nature": null, "origin": "insee", "status": "validated"}]}
```
`import_registry(registry, data, ref: RefData | None = None)` : accepte `version` 1 (lieux convertis par `levels_from_v1`) et 2 ; toute autre version → `RegistryFormatError` (message v1 inchangé). Règles de conflit inchangées.

- [ ] **Step 1 : tests qui échouent** : `test_export_is_version_2_with_levels` (un lieu Marconne à 5 niveaux, l'export contient `"version": 2` et les 5 niveaux dans l'ordre), `test_round_trip_keeps_levels_and_proposals` (export puis import dans un référentiel vide : `place.levels` identiques, statuts compris), `test_import_v1_document` (document v1 avec Lille + `former_name` Lomme : lieu créé avec `Lomme` proposé au rang 0 quand `ref` est donné, conflits d'écritures comme en v1), `test_invalid_level_rejected` (niveau sans `name` → `RegistryFormatError`, rien écrit).
- [ ] **Step 2 : vérifier l'échec**, **Step 3 : implémenter**, **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/store -v`.
- [ ] **Step 5 : commit** `feat(atelier): registry export format version 2 with levels`.

---

### Task 10 : le projet montre des chaînes de niveaux

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/project.py` (docstring comprise)
- Modify : `atelier/tests/test_project.py`

**Interfaces :**
- Consumes : `Cluster.levels`, `postal_code`, `alternatives` (Task 6) ; `Place` (Task 7).
- Produces :

```python
@dataclass(frozen=True)
class ClusterView:
    cluster: Cluster              # cluster.levels = chaîne du lieu (registre) ou des règles
    state: ClusterState
    occurrences: int
    parent_id: str | None
    provisional_name: str | None
    place_id: str | None = None
    from_registry: bool = False   # remplace `origins` : True quand cluster.levels vient du référentiel
    historical_writings: dict[str, str] = field(default_factory=dict)
```
`historical_writings` : pour un cluster qui est un lieu du référentiel, les écritures dont la décomposition a un `historical` qui n'est pas la `commune_historique` validée du lieu → nom de cette ancienne commune. C'est ce qui signale un lieu v1 qui mêle Lille et Lomme.

- [ ] **Step 1 : tests qui échouent** (et adapter les tests v1 qui lisent `proposal`/`origins`) : `test_marconne_and_hesdin_are_separate_clusters` (.gw synthétique avec des personnes fictives, lieux `Marconne, Pas-de-Calais`, `Hesdin, Pas-de-Calais`, `Hesdin-la-Forêt`), `test_place_cluster_shows_registry_levels` (`from_registry is True`, niveaux = ceux du référentiel, propositions comprises), `test_historical_writings_flag_merged_place` (lieu Lille validé avec `Lille` et `Lomme` → `historical_writings == {"Lomme": "Lomme"}`).
- [ ] **Step 2 : vérifier l'échec**, **Step 3 : implémenter**, **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/test_project.py atelier/tests/places atelier/tests/store -v`.
- [ ] **Step 5 : commit** `feat(atelier): project views carry level chains`.

---

### Task 11 : export pivot (`lieux` modifiée, `niveaux_lieux`)

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/export/pivot.py`, `export/LISEZMOI.txt`
- Modify : `atelier/tests/export/test_pivot.py`, `atelier/tests/export/test_archive.py`

**Interfaces :**
- Consumes : `french_view`, `view_origins`, `chain_label`, `validated` (Task 3) ; `PlaceRegistry.place` (Task 7).
- Produces :
  - `LIEUX` : `lieu_id`, `commune`, `code_insee`, `code_postal`, `departement`, `region`, `pays`, `commune_historique`, `code_insee_historique`, `libelle`, `latitude`, `longitude`, puis `<colonne>_origine` pour les huit premières colonnes après `lieu_id`. `ancien_nom` disparaît.
  - `NIVEAUX_LIEUX` (`primary_key=None` ou `("lieu_id", "rang")` selon ce que `TableSpec` accepte) : `lieu_id`, `rang`, `nom`, `nom_ecrit`, `type`, `nature`, `identifiant`, `source`, `debut`, `fin`, `latitude`, `longitude`, `origine` ; niveaux validés seulement, renumérotés.
  - `ORIGIN_VALUES = {"written": "ecrit", "rule": "regle", "manual": "manuel", "insee": "insee", "paris": "paris", "dicotopo": "dicotopo", "geonames": "geonames", "llm": "llm"}`.
  - `build_pivot` ajoute `niveaux_lieux` juste après `lieux`.
  - `LISEZMOI.txt` : paragraphe « Niveaux » (une ligne par niveau dans `niveaux_lieux`, du plus précis au plus large ; `lieux` donne la vue française et `libelle`), liste des origines mise à jour, mention que les anciennes communes viennent du COG (Licence Ouverte 2.0).

- [ ] **Step 1 : tests qui échouent** : `test_lieux_columns` (liste exacte ci-dessus), `test_niveaux_lieux_rows` (lieu Marconne : 5 lignes, `rang` 0..4, ligne 0 `type="commune_historique"`, `identifiant="62549"`, `nature="deleguee"`, `fin="2025-01-01"`, `origine="insee"`, `source="COG 2026"`), `test_proposed_levels_not_exported` (lieu avec un niveau proposé au rang 0 : absent de `niveaux_lieux`, rangs repartent à 0, `commune_historique` vide dans `lieux`), `test_libelle` (`"Marconne, Hesdin-la-Forêt, Pas-de-Calais, Hauts-de-France, France"`), `test_readme_mentions_levels` (`"niveaux_lieux"` et `"ecrit"` dans `LISEZMOI.txt` de l'archive).
- [ ] **Step 2 : vérifier l'échec**, **Step 3 : implémenter**, **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier/tests/export -v`.
- [ ] **Step 5 : commit** `feat(atelier): export level chains and the historical commune`.

---

### Task 12 : API web par niveaux

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/web/schemas.py`, `web/app.py`, `cli.py` (`PlaceRegistry(path, ref)`)
- Modify : `atelier/tests/web/test_api.py`, `atelier/tests/test_cli.py` si besoin

**Interfaces :**
- Consumes : Tasks 3, 7, 10.
- Produces :

```python
class LevelModel(BaseModel):     # entrée et sortie
    rank: int
    name: str
    written: str | None = None
    type: str | None = None
    identifier: str | None = None
    source: str | None = None
    start: str | None = None
    end: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    nature: HistoricalNature | None = None
    origin: LevelOrigin = "manual"
    status: LevelStatus = "validated"

class ClusterDetail(BaseModel):  # proposal/origins remplacés par :
    levels: list[LevelModel]
    postal_code: str | None
    view: dict[ViewField, str]           # french_view, en lecture seule
    view_origins: dict[ViewField, LevelOrigin]
    from_registry: bool
    alternatives: list[list[LevelModel]]
    historical_writings: dict[str, str]
    # (+ champs v1 inchangés : id, label, state, confidence, occurrences, parent_id, provisional_name, place_id, complements, writings)

class ValidateIn(BaseModel):
    levels: list[LevelModel]
    postal_code: str | None
    checked: list[str]

class LevelsIn(BaseModel):
    levels: list[LevelModel]
    postal_code: str | None

class PlaceOut(BaseModel):
    place_id: str
    levels: list[LevelModel]
    postal_code: str | None
    view: dict[ViewField, str]

class LevelTypeOut(BaseModel):
    value: str
    label: str
# ProjectInfo gagne : level_types: list[LevelTypeOut]  (FRENCH_TYPES puis FOREIGN_TYPES, avec TYPE_LABELS)
```

Routes :
- `POST /api/clusters/{id}/validate` : corps `ValidateIn`. Origine de chaque niveau envoyé : celle du niveau identique (même `name`, `type`, `identifier`) de `view.cluster.levels`, sinon `manual` ; idem pour le code postal. `check_chain` après `renumber` ; `ValueError` → 400 avec son message.
- `PUT /api/places/{place_id}/levels` : corps `LevelsIn` → `set_levels` ; remplace `PATCH /api/places/{place_id}` (supprimé).
- `POST /api/places/{place_id}/levels/{rank}/accept` et `.../refuse` → `accept_proposal` / `refuse_proposal` ; 404 si le lieu ou le rang n'existe pas, 409 si le niveau n'est pas proposé.
- Toutes ces actions empilent leur entrée de journal dans la pile d'annulation, comme en v1.

- [ ] **Step 1 : tests qui échouent** : `test_detail_has_levels_and_view` (cluster Marconne : `levels[0].type == "commune_historique"`, `view["commune"] == "Hesdin-la-Forêt"`), `test_validate_with_levels_keeps_rule_origins` (niveaux renvoyés tels quels → origines `insee`/`written` ; un nom modifié → `manual`), `test_validate_rejects_bad_levels` (paramétré : `levels=[]`, nom vide, `type="Comté"`, latitude 200 → 400, message en français, `registry.decisions` inchangé), `test_put_levels_and_undo`, `test_accept_and_refuse_proposal_routes` (lieu migré avec Lomme proposé), `test_project_lists_level_types`.
- [ ] **Step 2 : vérifier l'échec**, **Step 3 : implémenter**, **Step 4 : vérifier** — `uv run --package prosopo-gw-atelier python -m pytest atelier -v` : **toute la suite passe** à partir de cette tâche ; ruff et mypy propres.
- [ ] **Step 5 : commit** `feat(atelier): level chain API for clusters and places`.

---

### Task 13 : éditeur de chaîne de niveaux dans l'écran

**Files :**
- Modify : `atelier/src/prosopo_gw_atelier/web/static/app.js` (`FIELDS`, `ALWAYS_SHOWN`, `shownFields`, `renderForm`, envoi de la validation, correction d'un lieu), `web/static/app.css`
- Modify : `atelier/tests/web/test_static.py`

**Interfaces :**
- Consumes : routes et schémas de la Task 12.

Comportement (spec § 9) :
- Au-dessus : les cases françaises de `detail.view` en lecture seule, chacune avec son origine (libellés v1 ; « Ancien nom » devient « Commune historique » et « Code INSEE historique »).
- Dessous : la chaîne, une ligne par niveau du plus précis au plus large : nom (champ texte), type (champ texte avec `<datalist>` des `level_types`, libellé affiché), origine (pastille), boutons monter, descendre, retirer ; bouton « Ajouter un niveau » en bas. Code postal : un champ à part, sous la chaîne.
- Un niveau `proposed` s'affiche en retrait, avec sa source et deux boutons « Accepter » / « Refuser » (routes `accept`/`refuse` pour un lieu du référentiel ; pour une proposition de règles non encore validée, accepter l'intègre simplement à la chaîne en cours d'édition).
- `detail.alternatives` : encadré « Autre lecture possible : <libellé> » avec « Retenir cette lecture », qui remplace la chaîne en cours d'édition.
- `detail.historical_writings` non vide : avertissement « Ces écritures désignent une ancienne commune : … Séparez-les pour en faire un lieu distinct. » avec le bouton de scission existant.
- « Valider » envoie `{levels, postal_code, checked}` ; « Enregistrer » sur un lieu du référentiel envoie `PUT /api/places/{id}/levels`.
- Les erreurs 400 s'affichent avec `showMessage` comme en v1.

- [ ] **Step 1 : tests statiques qui échouent** dans `test_static.py` : `app.js` contient `"/levels"`, `"accept"`, `"refuse"`, `"Retenir cette lecture"`, `"Ajouter un niveau"`, `"level_types"` ; ne contient plus `"former_name"` ni `"Ancien nom"`.
- [ ] **Step 2 : vérifier l'échec**, **Step 3 : implémenter**, **Step 4 : vérifier** les tests.
- [ ] **Step 5 : essai dans le navigateur** (skill `run` ou `claude-in-chrome`) sur un `.gw` **synthétique** contenant `Marconne, Pas-de-Calais`, `Hesdin, Pas-de-Calais`, `Winnipeg, , , Manitoba, Canada`, `Storrington, , East Sussex, England, Royaume-Uni`, `Sainte-Austreberthe` : valider Marconne, réordonner un niveau de Storrington, retenir l'autre lecture de Sainte-Austreberthe, annuler, exporter ; vérifier `niveaux_lieux.csv` dans le zip. Aucune capture d'écran versionnée.
- [ ] **Step 6 : commit** `feat(atelier): edit place level chains on the validation screen`.

---

### Task 14 : documentation

**Files :**
- Modify : `atelier/doc/design_v1.md` (renvoi en tête vers le spec du 8 novembre pour le modèle à niveaux ; § pivot : `ancien_nom` remplacé)
- Modify : `atelier/README.md` (§ données de référence : colonnes de `historique.csv.gz` ; § export : `niveaux_lieux`)
- Modify : `docs/reflexions/points-ouverts.md` § 5 (retirer « colonne `MOD` exigée sans être utilisée » ; ajouter : « une nouvelle écriture rattachée à un lieu existant ne propose pas ses niveaux écrits manquants »)

- [ ] **Step 1 : rédiger** (français, phrases courtes, pas de nom de personne réelle).
- [ ] **Step 2 : vérifier** — suite complète, ruff check, ruff format --check, mypy (commandes des Global Constraints) : tout passe.
- [ ] **Step 3 : commit** `docs(atelier): document level chains and historical communes`.
