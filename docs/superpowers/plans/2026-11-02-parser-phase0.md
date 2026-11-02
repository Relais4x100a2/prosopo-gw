# Parser `.gw` : phase 0 — plan d'exécution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre la mesure de fidélité du parser reproductible par une commande, publier le tableau de référence des cinq informations clés avant toute correction, et consigner la trace exacte du plantage de l'application.

**Architecture:** L'oracle GeneWeb (filtre → `gwc` → `gwu` → `rt.gw`) tourne dans un conteneur jetable construit depuis le binaire officiel du tag `v7.1.0-beta2` ; un comparateur Python unique apparie familles, personnes et événements entre notre `Genealogy` et la relecture de `rt.gw`, et sort des comptages agrégés par champ. Un parcours `AppTest` des pages Streamlit et une sonde de l'API REST capturent les exceptions sur la base réelle, hors dépôt.

**Tech Stack:** Python 3.11 (`uv`, workspace), pytest, Docker 28, GeneWeb 7.1.0-beta2 (binaire officiel), `streamlit.testing.v1.AppTest`, `fastapi.testclient`.

**Spec:** `core/doc/parser_finalisation_design.md` (§ 3, 5.7, 5.8, 5.9, 6, 7 phase 0, 9.2) ; état des lieux : `core/doc/parser_fidelity_audit.md`.

## Global Constraints

- Dépôt **public** : aucun `*.gw` réel, aucun nom, lieu, date de vraie personne, ni **nom de fichier** de base réelle dans le code, les tests, la doc, les messages de commit. Les sorties d'oracle et de sonde ne contiennent que des comptages agrégés et des valeurs masquées (chiffres → `9`, lettres → `a`).
- La base réelle est désignée par la variable d'environnement `GENEWEB_REAL_BASE` (chemin absolu hors dépôt, lecture seule) ; jamais recopiée, jamais écrite dans un fichier suivi.
- `uv` exclusivement : `uv run --package geneweb-py …` depuis la racine ; `uv run --package geneweb-app …` pour l'app.
- `core/src` reste compatible Python 3.8 ; `core/tools` et `app/` peuvent utiliser Python 3.11.
- Lint : `ruff check` + `ruff format --check` propres sur tout fichier Python ajouté ; mypy n'est exigé que sur `core/src/geneweb_py`.
- Couverture `core` ≥ 80 % : inchangée par ce plan (les outils sont hors `geneweb_py`).
- Commits : `type(scope): message` en anglais, un sujet par commit, `git add` par chemins explicites, puis `git diff --cached --name-only`. Pas de `git push`. Chaque message se termine par la ligne d'attribution `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- `Dockerfile.dockerignore` de l'app n'est pas élargi. `core/tools/oracle/` n'entre pas dans l'image de l'app.
- Référence OCaml qui fait foi : dépôt officiel `github.com/geneweb/geneweb`, tag `v7.1.0-beta2` (commit `2115f6af`).

## Review Focus

Cas que la spec implique mais qu'aucune tâche ne testerait sans les lignes ci-dessous (chaque ligne a son test dans la tâche indiquée) :

1. **Base de plus de 10 Mo** : le comparateur doit donner le même tableau en mode complet et en mode streaming ; une divergence est un résultat, pas une erreur → tâche 3, test `test_compare_both_modes_same_table`.
2. **Personne présente d'un seul côté** (gwc a fusionné ou refusé une personne) : comptée dans « non appariées », jamais une exception → tâche 3, test `test_compare_unmatched_person_counted`.
3. **`fevt` conservé par le filtre** : un bloc `fevt` du fichier source arrive intact dans `in.gw` → tâche 1, test `test_filter_keeps_fevt_block`.
4. **Dossier de sortie dans le dépôt** : `run.sh` refuse et s'arrête avant d'écrire quoi que ce soit → tâche 1, étape de vérification manuelle (`run.sh … core/doc` doit échouer avec le message `refus : dossier de sortie dans le dépôt`).
5. **Exemple d'écart contenant un nom réel** : les exemples du tableau passent par `mask()` avant toute impression → tâche 2, test `test_mask_hides_letters_and_digits`.

---

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `core/tools/oracle/Dockerfile` | image `geneweb-oracle:7.1.0-beta2` (binaire officiel du tag) |
| `core/tools/oracle/run.sh` | `run.sh <base.gw> <dossier_sortie>` : filtre, `gwc`, `gwu`, logs |
| `core/tools/oracle/filter.py` | copie filtrée (retire `wnote`, `comm` répétés ; garde `fevt`) |
| `core/tools/oracle/compare.py` | apparie et compte : familles, personnes, événements ; tableau Markdown |
| `core/tools/oracle/api_probe.py` | sonde de l'API REST sur une base (session, recherche, événements) |
| `core/tools/oracle/README.md` | mode d'emploi, rappel « rien à versionner » |
| `core/tools/oracle/.gitignore` | `*.gw`, `*.log`, `out/`, `*.json`, `*.md` sauf README |
| `core/tools/oracle/__init__.py` | vide (rend `oracle.compare` importable par les tests) |
| `core/tests/unit/test_oracle_filter.py` | tests de `filter.py` |
| `core/tests/unit/test_oracle_compare.py` | tests de `compare.py` sur fixtures synthétiques |
| `core/tests/fixtures/oracle_source.gw`, `oracle_rt.gw` | paire synthétique source / relecture `gwu` |
| `app/docker/geneweb-app/tests/smoke_real_base.py` | parcours `AppTest` des pages sur base réelle |
| `core/pyproject.toml` | `pythonpath = ["src", "tools"]` |
| `.github/workflows/ci.yml` | ruff sur `core/tools` en plus |
| `core/doc/parser_fidelity_audit.md` | nouvelle section « 5. Mesures » (tableau de référence, trace du plantage) |

Choix de l'auteur, hors spec : le `Dockerfile` installe le **binaire officiel** `geneweb-7.1.0-beta2-linux.zip` publié pour le tag au lieu de compiler les sources OCaml. Même tag, même code, même `gwc`/`gwu` ; on évite une compilation `opam` de vingt à quarante minutes. Les sources du tag restent la référence pour les règles recopiées.

---

### Task 1 : Oracle GeneWeb versionné (image, filtre, lanceur)

**Files:**
- Create: `core/tools/oracle/Dockerfile`, `core/tools/oracle/run.sh`, `core/tools/oracle/filter.py`, `core/tools/oracle/__init__.py`, `core/tools/oracle/.gitignore`, `core/tools/oracle/README.md`
- Modify: `core/pyproject.toml` (`[tool.pytest.ini_options] pythonpath`), `.github/workflows/ci.yml:38,41`
- Test: `core/tests/unit/test_oracle_filter.py`

**Interfaces:**
- Produces: `filter.filter_lines(lines: list[str], drop: list[re.Pattern[str]]) -> tuple[list[str], collections.Counter[str]]` ; CLI `python filter.py <src.gw> <dst.gw> [--drop REGEX]...` (défaut `^wnote `), imprime le `Counter` en JSON sur stdout.
- Produces: `run.sh <base.gw> <dossier_sortie>` écrit `in.gw`, `filter.log`, `gwc.log`, `gwu.log`, `rt.gw` dans le dossier ; code de retour 0 si `gwu` a produit `rt.gw`. Variable `ORACLE_IMAGE` (défaut `geneweb-oracle:7.1.0-beta2`).

- [ ] **Step 1 : tests de `filter.py`**

```python
# core/tests/unit/test_oracle_filter.py
import re
from oracle.filter import filter_lines

def test_filter_drops_wnote_and_repeated_comm():
    lines = ["fam DUPONT Jean + MARTIN Anne", "comm a", "comm b", "wnote x", "end"]
    out, counts = filter_lines(lines, [re.compile(r"^wnote ")])
    assert out == ["fam DUPONT Jean + MARTIN Anne", "comm a", "end"]
    assert counts["comm répété"] == 1 and counts["^wnote "] == 1

def test_filter_keeps_fevt_block():
    lines = ["fam DUPONT Jean + MARTIN Anne", "fevt", "#marr 1900 #p Paris", "end fevt"]
    out, _ = filter_lines(lines, [])
    assert out == lines
```

- [ ] **Step 2 : lancer, vérifier l'échec**

Run : `uv run --package geneweb-py python -m pytest core/tests/unit/test_oracle_filter.py -q`
Attendu : `ModuleNotFoundError: No module named 'oracle'`

- [ ] **Step 3 : `core/tools/oracle/__init__.py` vide, `pythonpath = ["src", "tools"]` dans `core/pyproject.toml`, puis `filter.py`**

`filter_lines` : une ligne `comm …` est retirée si la dernière ligne conservée commence par `comm ` ; les blocs `fevt` ne sont plus traités. `main()` lit en UTF-8, normalise `\r\n`, écrit la copie, imprime `json.dumps(dict(counts), ensure_ascii=False)`.

- [ ] **Step 4 : tests verts**

Run : même commande. Attendu : `2 passed`.

- [ ] **Step 5 : `Dockerfile`**

Base `debian:bookworm-slim` ; `ARG GENEWEB_TAG=v7.1.0-beta2` ; télécharge `https://github.com/geneweb/geneweb/releases/download/${GENEWEB_TAG}/geneweb-7.1.0-beta2-linux.zip`, dézippe sous `/opt/geneweb`, ajoute le dossier contenant `gwc` et `gwu` au `PATH` (vérifier la disposition de l'archive au build par `find /opt/geneweb -name gwc`). `ENTRYPOINT ["sh","-c"]` absent : image nue, `run.sh` passe la commande.

- [ ] **Step 6 : construire et vérifier**

Run : `docker build -t geneweb-oracle:7.1.0-beta2 core/tools/oracle && docker run --rm geneweb-oracle:7.1.0-beta2 gwc -help 2>&1 | head -3`
Attendu : l'usage de `gwc` s'affiche.

- [ ] **Step 7 : `run.sh`**

`set -eu` ; deux arguments obligatoires sinon usage et code 2 ; `mkdir -p` du dossier puis refus si `git -C "$OUT" rev-parse --is-inside-work-tree` renvoie `true` (message exact : `refus : dossier de sortie dans le dépôt`, code 3) ; `python3 "$(dirname "$0")/filter.py" "$BASE" "$OUT/in.gw" > "$OUT/filter.log"` ; `docker run --rm --user "$(id -u):$(id -g)" -v "$OUT:/out" "$ORACLE_IMAGE" sh -c 'mkdir -p /tmp/w && cp /out/in.gw /tmp/w/src.gw && cd /tmp/w && gwc -f -o b src.gw > /out/gwc.log 2>&1; echo gwc=$?; gwu b -o /out/rt.gw > /out/gwu.log 2>&1; echo gwu=$?'` ; affiche à la fin le nombre de lignes `fam ` de `in.gw` et de `rt.gw`.

- [ ] **Step 8 : vérifier le refus et un passage sur fixture**

Run : `core/tools/oracle/run.sh core/tests/fixtures/sample.gw core/doc/out; echo code=$?`
Attendu : `refus : dossier de sortie dans le dépôt`, `code=3`, aucun fichier créé dans `core/doc/out` (le `mkdir -p` doit venir **après** le test, ou être annulé).
Run : `core/tools/oracle/run.sh core/tests/fixtures/sample.gw "$HOME/oracle_out/fixture"` (prendre la plus grosse fixture synthétique de `core/tests/fixtures/`).
Attendu : `gwc=0 gwu=0`, `rt.gw` non vide.

- [ ] **Step 9 : `.gitignore` local, `README.md`, CI**

`.gitignore` : `*.gw`, `*.gwb/`, `*.log`, `*.json`, `out/`. README : usage des trois commandes, variable `GENEWEB_REAL_BASE`, phrase « aucune sortie n'est à versionner », choix du binaire officiel. CI : ajouter `core/tools` aux deux lignes ruff (`check` et `format --check`).
Run : `uv run --package geneweb-py ruff check core/tools core/tests --ignore E501 && uv run --package geneweb-py ruff format --check core/tools core/tests`
Attendu : aucune erreur.

- [ ] **Step 10 : commit**

```bash
git add core/tools/oracle/Dockerfile core/tools/oracle/run.sh core/tools/oracle/filter.py core/tools/oracle/__init__.py core/tools/oracle/.gitignore core/tools/oracle/README.md core/tests/unit/test_oracle_filter.py core/pyproject.toml .github/workflows/ci.yml
git diff --cached --name-only
git commit -m "chore(oracle): version GeneWeb 7.1 oracle tooling (image, filter, runner)"
```

---

### Task 2 : `compare.py`, familles (remplace `oracle_cmp.py`)

**Files:**
- Create: `core/tools/oracle/compare.py`, `core/tests/fixtures/oracle_source.gw`, `core/tests/fixtures/oracle_rt.gw`
- Test: `core/tests/unit/test_oracle_compare.py`

**Interfaces:**
- Produces :
  - `copy_decode(word: str) -> str`, `cut_space(s: str) -> str`, `norm(value: Optional[str]) -> str` (décodage GeneWeb d'une valeur stockée, `None` → `""`) ;
  - `mask(value: str) -> str` (chiffres → `9`, lettres → `a`, tronqué à 60) ;
  - `@dataclass class FieldStat: present: int = 0; equal: int = 0; raw_underscore: int = 0; examples: list[tuple[str, str]]` avec `add(ref: str, got: str) -> None` (compte `present` si `ref` non vide, `equal` si `norm` égaux, `raw_underscore` si `got` contient `_`, garde 5 exemples masqués) et propriété `rate: Optional[float]` ;
  - `load(path: str, stream: bool) -> Genealogy` (`GeneWebParser(validate=False, stream_mode=stream).parse_file`) ;
  - `person_key(p: Person) -> tuple[str, str, int]` (nom et prénom décodés, occurrence) ;
  - `compare_families(got: Genealogy, ref: Genealogy, stats: dict[str, FieldStat]) -> int` : apparie par ordre d'apparition avec contrôle des clés des conjoints, renvoie le nombre de familles non appariées ; champs `fam.marriage_date`, `fam.marriage_place`, `fam.marriage_source`, `fam.kind`, `fam.divorce`, `fam.family_source`, `fam.witnesses` (nombre de témoins) ;
  - `render_table(stats: dict[str, FieldStat], unmatched: dict[str, int]) -> str` Markdown : colonnes `champ | présents (gwu) | identiques | écarts | encore bruts | taux` ;
  - CLI `python compare.py <source.gw> <rt.gw> [--stream] [--examples]`.

- [ ] **Step 1 : fixtures synthétiques**

`oracle_source.gw` : trois familles `DUPONT Jean` / `MARTIN Anne`, `BERNARD Paul` / `PETIT Marie`, `MOREAU Luc` / `? ?`, avec dates, `#mp`, `#ms`, un `wit`, un bloc `fevt`, des enfants avec `#occu`, `#bp`, `#src`, un bloc `pevt`. `oracle_rt.gw` : même contenu réécrit au style `gwu` (ordre canonique, infos des enfants sur la ligne enfant) avec **deux écarts volontaires** : `#ms` absent sur la deuxième famille, lieu de naissance différent pour un enfant. Noms fictifs uniquement.

- [ ] **Step 2 : tests**

```python
# core/tests/unit/test_oracle_compare.py
from pathlib import Path
from oracle.compare import FieldStat, compare_families, load, mask, norm, render_table

FIX = Path(__file__).resolve().parents[1] / "fixtures"

def test_mask_hides_letters_and_digits():
    assert mask("Paris 1900, rue Émile") == "aaaaa 9999, aaa aaaaa"

def test_norm_decodes_underscore_and_escape():
    assert norm("Saint_Denis") == "Saint Denis"
    assert norm(r"rue\_haute") == "rue_haute"
    assert norm(None) == ""

def test_compare_families_counts_known_gap():
    got, ref = load(str(FIX / "oracle_source.gw"), False), load(str(FIX / "oracle_rt.gw"), False)
    stats: dict[str, FieldStat] = {}
    assert compare_families(got, ref, stats) == 0
    assert stats["fam.marriage_date"].present == 3
    assert stats["fam.marriage_date"].equal == 3
    assert stats["fam.marriage_source"].present == 1   # retiré volontairement dans rt sur la 2e famille

def test_render_table_has_one_row_per_field():
    s = {"fam.marriage_date": FieldStat()}
    s["fam.marriage_date"].add("1900", "1900")
    out = render_table(s, {"familles": 0})
    assert "| fam.marriage_date | 1 | 1 | 0 | 0 | 100.0 % |" in out
```

- [ ] **Step 3 : échec attendu**

Run : `uv run --package geneweb-py python -m pytest core/tests/unit/test_oracle_compare.py -q`
Attendu : `ModuleNotFoundError` ou `ImportError` sur `oracle.compare`.

- [ ] **Step 4 : implémenter `compare.py` (partie familles)**

Porter `parse_rt`/`ours` de l'ancien `oracle_cmp.py` sur la base commune `load()` des deux côtés : les deux `Genealogy` sont parcourues par ordre d'apparition des familles (`genealogy.families.values()`), clé `(person_key(husband), person_key(wife))` ; en cas de désaccord de clé, la famille est comptée non appariée et on avance du côté dont la clé est « en retard » (recherche sur une fenêtre de 3). `fam.kind` = statut de mariage ou premier qualificatif ; `fam.divorce` = texte brut de la date de divorce, `"div"` si statut divorcé sans date, `""` sinon ; `fam.witnesses` = `str(len(fam.witnesses))`.

- [ ] **Step 5 : tests verts, lint**

Run : tests ci-dessus puis `uv run --package geneweb-py ruff check core/tools core/tests --ignore E501 && uv run --package geneweb-py ruff format core/tools core/tests`
Attendu : `4 passed`, lint propre.

- [ ] **Step 6 : commit**

```bash
git add core/tools/oracle/compare.py core/tests/unit/test_oracle_compare.py core/tests/fixtures/oracle_source.gw core/tests/fixtures/oracle_rt.gw
git commit -m "feat(oracle): add family field comparator against gwu round trip"
```

---

### Task 3 : `compare.py`, personnes et événements (remplace `oracle_psrc.py`, `oracle_child.py`)

**Files:**
- Modify: `core/tools/oracle/compare.py`
- Test: `core/tests/unit/test_oracle_compare.py`

**Interfaces:**
- Consumes : `FieldStat`, `person_key`, `norm`, `load`, `render_table` (tâche 2).
- Produces :
  - `compare_persons(got, ref, stats) -> int` : apparie par `person_key`, renvoie le nombre de personnes de `ref` sans équivalent ; champs `pers.birth_date`, `pers.birth_place`, `pers.birth_source`, `pers.baptism_date`, `pers.baptism_place`, `pers.baptism_source`, `pers.death_date`, `pers.death_place`, `pers.death_source`, `pers.burial_place`, `pers.burial_source`, `pers.occupation`, `pers.person_source` ; dates comparées sur `Date.raw_text` ;
  - `compare_events(got, ref, stats) -> int` : pour chaque personne appariée, événements `pevt` appariés par `(event_type_raw ou event_type.value, norm(date.raw_text))` ; champs `pevt.place`, `pevt.source`, `pevt.witnesses` (nombre) ; de même pour les `fevt` des familles appariées (`fevt.date`, `fevt.place`, `fevt.source`, `fevt.witnesses`) ; renvoie le nombre d'événements de `ref` sans équivalent ;
  - `naive_tag_counts(text: str) -> dict[str, int]` : nombre d'occurrences de `#bp`, `#bs`, `#dp`, `#ds`, `#occu`, `#src`, `#mp`, `#ms`, lignes `wit ` dans `rt.gw` (découpage sur espaces, hors blocs `notes`) ; ajouté au rapport comme ligne « contrôle naïf » pour détecter une erreur de lecture partagée (§ 6 de la spec) ;
  - `main(argv: list[str]) -> int` : charge les deux fichiers dans le mode demandé, enchaîne les trois comparaisons, imprime le tableau, les non-appariés, le contrôle naïf, et les exemples masqués si `--examples`.

- [ ] **Step 1 : tests**

```python
def test_compare_persons_counts_known_gap():
    got, ref = load(str(FIX / "oracle_source.gw"), False), load(str(FIX / "oracle_rt.gw"), False)
    stats: dict[str, FieldStat] = {}
    assert compare_persons(got, ref, stats) == 0
    bp = stats["pers.birth_place"]
    assert bp.present >= 2 and bp.present - bp.equal == 1   # un lieu modifié volontairement dans rt

def test_compare_unmatched_person_counted(tmp_path):
    src = (FIX / "oracle_source.gw").read_text(encoding="utf-8")
    extra = src + "\nfam DURAND Marc + ROUX Lise\n"
    p = tmp_path / "rt_plus.gw"; p.write_text(extra, encoding="utf-8")
    got, ref = load(str(FIX / "oracle_source.gw"), False), load(str(p), False)
    assert compare_persons(got, ref, {}) == 2

def test_compare_events_pairs_pevt_by_type_and_date():
    got, ref = load(str(FIX / "oracle_source.gw"), False), load(str(FIX / "oracle_rt.gw"), False)
    stats: dict[str, FieldStat] = {}
    assert compare_events(got, ref, stats) == 0
    assert stats["pevt.place"].present >= 1

def test_compare_both_modes_same_table():
    a = render_table(*_run(FIX / "oracle_source.gw", FIX / "oracle_rt.gw", stream=False))
    b = render_table(*_run(FIX / "oracle_source.gw", FIX / "oracle_rt.gw", stream=True))
    assert a == b

def test_naive_tag_counts():
    assert naive_tag_counts("- h Pierre #bp Paris #src x\nwit m: DUPONT Luc\n")["#bp"] == 1
```

`_run` : petit helper du module de test qui enchaîne `load` × 2 et les trois `compare_*`, renvoie `(stats, unmatched)`.

- [ ] **Step 2 : échec attendu**

Run : `uv run --package geneweb-py python -m pytest core/tests/unit/test_oracle_compare.py -q`
Attendu : `ImportError` sur `compare_persons`.

- [ ] **Step 3 : implémenter**

Personnes : dictionnaire `person_key → Person` de chaque côté ; parcours sur les clés de `ref`. Événements : pour les personnes appariées, dictionnaire `(type, date) → PersonalEvent` ; un doublon de clé prend le premier. `main` utilise `argparse`.

- [ ] **Step 4 : tests verts, lint**

Run : tests + ruff comme en tâche 2. Attendu : `9 passed`.

- [ ] **Step 5 : commit**

```bash
git add core/tools/oracle/compare.py core/tests/unit/test_oracle_compare.py
git commit -m "feat(oracle): compare persons and events, add naive tag control"
```

---

### Task 4 : rejouer l'audit et publier le tableau de référence

**Files:**
- Modify: `core/doc/parser_fidelity_audit.md` (nouvelle section « 5. Mesures »)

**Interfaces:**
- Consumes : `run.sh`, `compare.py` (tâches 1 à 3) ; `GENEWEB_REAL_BASE` fourni par l'environnement.

- [ ] **Step 1 : oracle sur la base réelle**

Run : `core/tools/oracle/run.sh "$GENEWEB_REAL_BASE" "$HOME/oracle_out/big"`
Attendu : `gwc=0 gwu=0` ; `filter.log` montre `wnote` et `comm répété` retirés, aucune mention de `fevt`. Noter les nombres de `fam ` d'`in.gw` et `rt.gw` (l'audit en attendait 2 875).

- [ ] **Step 2 : comparaison, deux modes**

Run : `uv run --package geneweb-py python core/tools/oracle/compare.py "$GENEWEB_REAL_BASE" "$HOME/oracle_out/big/rt.gw" > "$HOME/oracle_out/big/table_full.md"` puis la même avec `--stream` vers `table_stream.md`.
Attendu : lignes `fam.*` à 0 écart hors écarts expliqués (conjoint `? ?`, sexe incohérent), comme dans l'audit ; les lignes `pers.*` et `pevt.*` donnent la ligne de base ; `diff table_full.md table_stream.md` vide, ou différences notées.

- [ ] **Step 3 : vérifier le tableau avant publication**

Relire `table_full.md` : aucune valeur non masquée, aucun nom. Si une ligne surprend (taux à 0 % par exemple), vérifier avec `--examples` que c'est une lecture et non un défaut d'appariement, et corriger `compare.py` (tests d'abord) avant de publier.

- [ ] **Step 4 : section « 5. Mesures » de l'audit**

Ajouter la date, la commande exacte (avec `$GENEWEB_REAL_BASE`, jamais le chemin), les comptages (familles, personnes, événements, non appariés) et le tableau par champ dans les deux modes, puis une courte lecture : quels champs sont déjà au-dessus de 99 %, lesquels portent les pertes connues (§ 3.1 de l'audit : `#src` enfant, professions coupées, dates fausses, `\_`).

- [ ] **Step 5 : commit**

```bash
git add core/doc/parser_fidelity_audit.md core/doc/parser_finalisation_design.md
git commit -m "docs(parser): add phase 0 baseline table and finalisation design"
```

---

### Task 5 : trace du plantage de l'application

**Files:**
- Create: `app/docker/geneweb-app/tests/smoke_real_base.py`, `core/tools/oracle/api_probe.py`
- Modify: `core/doc/parser_fidelity_audit.md` (section 5, sous-partie « Application »)

**Interfaces:**
- Produces : `smoke_real_base.py` : variable `GENEWEB_REAL_BASE` obligatoire ; pour chaque fichier de `pages/` trié, `AppTest.from_file(page, default_timeout=900)`, `session_state` prépeuplé avec ce que la page d'upload produit (repérer les clés par `grep -n "session_state\[" pages/*.py`), `at.run()` ; sortie : une ligne par page `page | exceptions=N | widgets=N`, puis chaque trace écrite dans `$SMOKE_OUT/<page>.txt` (dossier hors dépôt, défaut `$HOME/oracle_out/smoke`). Code de retour = nombre total d'exceptions.
- Produces : `api_probe.py <base.gw>` : `fastapi.testclient.TestClient(app)` ; `POST /api/v1/sessions` (upload), puis `GET /api/v1/persons?query=<prénom de la première personne>`, `GET /api/v1/persons/{id}/events`, `GET /api/v1/events?person_id={id}`, `GET /api/v1/events?query=<même prénom>`, `GET /api/v1/events/stats/overview` ; imprime `route | statut | durée`, et la trace complète pour tout statut 500 ou exception. Le prénom n'est jamais imprimé.

- [ ] **Step 1 : reconstruire et relancer l'image de l'app**

Run : `docker compose -f app/docker-compose.yml up -d --build geneweb-app && sleep 20 && curl -fs http://localhost:8501/_stcore/health`
Attendu : `ok`. (La variable `API_KEY_OPENROUTER` peut rester vide pour ce test.)

- [ ] **Step 2 : `smoke_real_base.py`**

Écrire le script ; l'exécuter : `GENEWEB_REAL_BASE=… uv run --package geneweb-app python app/docker/geneweb-app/tests/smoke_real_base.py`
Attendu : une ligne par page ; toute exception est capturée dans `$SMOKE_OUT`, pas dans le terminal, sauf la première ligne de chaque trace.

- [ ] **Step 3 : `api_probe.py`**

Écrire le script ; l'exécuter : `uv run --package geneweb-py python core/tools/oracle/api_probe.py "$GENEWEB_REAL_BASE"`
Attendu : tableau des routes ; toute 500 est accompagnée de sa trace.

- [ ] **Step 4 : consigner**

Dans l'audit, sous-partie « Application » : pages parcourues, nombre d'exceptions par page, trace(s) sans valeur nominative (cadres `fichier:ligne` + message), résultat de la sonde API, et la phrase explicite « l'interface à trois onglets décrite par le responsable n'a pas été retrouvée ; trace capturée sur les pages existantes et l'API (spec § 9.2) ».

- [ ] **Step 5 : lint et commit**

Run : `uv run --package geneweb-py ruff check core/tools app/docker/geneweb-app/tests --ignore E501 && uv run --package geneweb-py ruff format --check core/tools app/docker/geneweb-app/tests`
```bash
git add app/docker/geneweb-app/tests/smoke_real_base.py core/tools/oracle/api_probe.py core/doc/parser_fidelity_audit.md
git commit -m "test(app): add real-base smoke run for Streamlit pages and REST API"
```

---

## Critère de passage de la phase 0 (spec § 7)

- [ ] L'oracle se rejoue par `run.sh` + `compare.py` sur la base réelle, dans les deux modes.
- [ ] Le tableau de référence des cinq informations clés est publié dans l'audit, section 5.
- [ ] La trace du plantage (ou son absence sur les pages existantes) est consignée, section 5.
- [ ] `uv run --package geneweb-py python -m pytest core -q` vert ; ruff propre sur `core/src core/tests core/tools`.
