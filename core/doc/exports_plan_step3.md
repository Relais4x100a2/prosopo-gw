# Export zip dans la webapp : plan d'implémentation de l'étape 3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** l'archive de l'export (étapes 1 et 2) se télécharge depuis l'API et depuis un bouton unique de l'onglet Export. Les anciens boutons disparaissent ; leurs routes restent.

**Architecture :**
- Le service de session expose deux méthodes : `export_bundle(now)` et `export_summary()`.
- Deux routes `GET` du routeur `genealogy` les servent : le zip, et un petit JSON de comptes pour la ligne de résumé.
- Le nom du fichier `.gw` est gardé, une fois assaini, dans l'entrée de session (pas dans `metadata.source_file`, qui reste `None`), puis transmis au service.
- Le front appelle les deux routes après `syncIgnoredWords()`.

**Tech Stack :** FastAPI, SlowAPI, pytest + `TestClient`, JS vanilla (`static/app.js`), tests statiques par regex (`tests/api/test_static_frontend.py`).

**Spec :** `core/doc/exports_design.md` (§ 5.1 nom de l'archive, § 5.3 route, § 7 webapp, § 10 tests).

## Global Constraints

- Nom de l'archive : `prosopo-<base>-<AAAA-MM-JJ>.zip`, où `<base>` est le nom du `.gw` chargé, sans extension (§ 5.1) ; `base_stem` / `archive_name` existent déjà dans `formats/table_writers.py`.
- Route : `GET /api/v1/genealogy/export/zip` ; « les routes d'export actuelles restent, sans bouton » (§ 5.3).
- Bouton : libellé exact « Télécharger les données (.zip) », avec une ligne qui résume le contenu : nombres de personnes, organisations, événements à classer, pistes (§ 7).
- Disparaissent : les boutons GEDCOM, JSON, XML, compagnon et les trois CSV ; leurs routes restent (§ 7).
- Pas de section « Pistes étendues » dans l'onglet Organisations (§ 7).
- Ne jamais commiter un fichier exporté : le zip contient des données personnelles.
- `genealogy.metadata.source_file` reste `None` en session (`test_source_file_not_stored`).
- Réponses de données : `Cache-Control: no-store`.
- CSP `default-src 'self'` : aucune ressource externe dans le front.
- Fixtures synthétiques uniquement ; couverture ≥ 80 % ; mypy à 0 erreur ; ruff propre.

## Review Focus

1. **Nom de fichier hostile à l'upload, ou service sans nom** (`../ma base "x".gw` ; `GenealogyService(g)` sans `source_name`) : l'archive s'appelle `prosopo-ma_base__x_-<date>.zip` ou `prosopo-base-<date>.zip`. L'en-tête `Content-Disposition` ne contient ni guillemet ni barre. Testé en Task 1 (`test_zip_name_from_unsafe_upload_name`).
2. **Mots ignorés réglés dans la session** (`PUT /organizations/ignored-words`) : ils valent pour le zip (clé `ignored_words` du compagnon, pistes filtrées) et pour le résumé. Testé en Task 1 (`test_zip_uses_session_ignored_words`).
3. **Session absente ou expirée** : 401 sur les deux routes, comme sur les autres routes de données. Testé en Task 1 (`test_export_routes_require_session`).
4. **Le résumé dit la même chose que le zip** : chaque compte égale le nombre de lignes du CSV correspondant dans l'archive. Testé en Task 1 (`test_summary_matches_zip_tables`).
5. **Base sans organisation ni note** : le zip reste complet (16 fichiers) et le résumé vaut 0 partout, sauf pour les personnes. Testé en Task 1 (`test_zip_for_base_without_organizations`).

---

### Task 1 : routes du zip et du résumé

**Files :**
- Modify: `core/src/geneweb_py/api/session_store.py` (`SessionEntry.source_name`, `create(..., source_name=None)`, `service()` le transmet)
- Modify: `core/src/geneweb_py/api/routers/sessions.py` (passe `safe_name` à `store.create`)
- Modify: `core/src/geneweb_py/api/services/genealogy_service.py` (paramètre `source_name`, méthodes `export_bundle`, `export_summary`)
- Modify: `core/src/geneweb_py/api/routers/genealogy.py` (deux routes, déclarées **avant** `/export/{format}`)
- Test: `core/tests/api/test_export_zip_route.py` (nouveau)

**Interfaces :**
- Consumes: `build_export_bundle(genealogy, index, shared, ignored_words, source_name, now) -> Tuple[str, bytes]` (`api/services/export_bundle.py`) ; `build_organization_tables(genealogy, index, shared, ignored_words) -> List[Table]`.
- Produces:
  - `SessionStore.create(genealogy: Genealogy, source_name: Optional[str] = None) -> Tuple[str, datetime]`
  - `GenealogyService.__init__(self, genealogy: Optional[Genealogy] = None, source_name: Optional[str] = None)`
  - `GenealogyService.export_bundle(self, now: datetime) -> Tuple[str, bytes]`
  - `GenealogyService.export_summary(self) -> Dict[str, int]`, clés exactes `personnes`, `organisations`, `a_classer`, `pistes`
  - `GET /api/v1/genealogy/export/zip` : `application/zip`, `Content-Disposition: attachment; filename="prosopo-<base>-<date>.zip"`, `Cache-Control: no-store`, limite `10/minute`
  - `GET /api/v1/genealogy/export/summary` : JSON `{"personnes", "organisations", "a_classer", "pistes"}`, limite `40/minute`

- [ ] **Step 1 : écrire les tests qui échouent**

Fixture : un `.gw` synthétique uploadé par `POST /api/v1/sessions/` sous le nom `base-test.gw`. Il contient une organisation (`#occu … #p [Banque Fictive] - Lyon` chez deux personnes), un événement libre non classé et une note de personne avec « usine ». Le helper `_session(client, gw, filename)` renvoie le jeton ; le schéma est celui de `tests/api/test_session_integration.py`.

```python
def test_zip_route_returns_named_archive(client):
    token = _session(client, GW, "base-test.gw")
    r = client.get("/api/v1/genealogy/export/zip", headers={"X-Session-Token": token})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["cache-control"] == "no-store"
    today = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="prosopo-base-test-{today}.zip"'
    )
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 16 and any(n.endswith("pistes.csv") for n in names)

def test_source_name_kept_out_of_metadata(client):
    token = _session(client, GW, "base-test.gw")
    entry = client.app.state.session_store._store[token]
    assert entry.genealogy.metadata.source_file is None
    assert entry.source_name == "base-test.gw"

def test_zip_name_from_unsafe_upload_name(client):           # Review Focus 1
    # upload '../ma base "x".gw' → prosopo-ma_base__x_-<date>.zip
    # (le routeur des sessions refuse un nom sans « .gw » : le repli « base » se teste
    #  sur le service, GenealogyService(g).export_bundle(now)[0] == f"prosopo-base-{now.date()}.zip")
    # l'en-tête ne contient qu'une paire de guillemets et aucun « / »

def test_zip_uses_session_ignored_words(client):              # Review Focus 2
    # PUT /api/v1/organizations/ignored-words {"words": ["usine"]}, puis zip :
    # compagnon["ignored_words"] contient "usine" ; aucune ligne de pistes.csv n'a "usine" dans mots

def test_export_routes_require_session(client):              # Review Focus 3
    for path in ("/api/v1/genealogy/export/zip", "/api/v1/genealogy/export/summary"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-Session-Token": "inconnu"}).status_code == 401

def test_summary_counts(client):
    # {"personnes": <nb de personnes de GW>, "organisations": 1, "a_classer": 1, "pistes": 1}

def test_summary_matches_zip_tables(client):                  # Review Focus 4
    # personnes / organisations / reste_a_classer / pistes : lignes du CSV (hors en-tête)
    # == summary["personnes"], ["organisations"], ["a_classer"], ["pistes"]

def test_zip_for_base_without_organizations(client):          # Review Focus 5
    # GW minimal (une famille, aucun événement ni note) : 16 fichiers,
    # summary == {"personnes": 2, "organisations": 0, "a_classer": 0, "pistes": 0}

def test_existing_export_routes_still_served(client):
    for fmt in ("gedcom", "json", "xml", "org-json", "organizations-csv",
                "organization-links-csv", "shared-experiences-csv"):
        assert client.get(f"/api/v1/genealogy/export/{fmt}", headers=h).status_code == 200
```

Lis les CSV avec `csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";")`. Les chemins des membres de l'archive viennent de `build_zip` : cherche-les par suffixe (`endswith("pistes.csv")`).

- [ ] **Step 2 : vérifier l'échec**

Run: `cd core && COLUMNS=200 uv run python -m pytest tests/api/test_export_zip_route.py -q`
Expected: échecs. `/export/zip` tombe dans `/export/{format}`, qui répond 400 « format non supporté » ; `entry.source_name` n'existe pas encore.

- [ ] **Step 3 : implémenter**

- `SessionEntry` reçoit `source_name: Optional[str] = None` ; `service()` crée `GenealogyService(genealogy=entry.genealogy, source_name=entry.source_name)`.
- `export_bundle(now)` appelle `build_export_bundle(self.genealogy, self.get_candidate_index(), self.get_shared_experiences(), self._ignored_words, self._source_name, now)`.
- `export_summary()` construit `build_organization_tables` avec les mêmes arguments. Ses comptes sont `len(genealogy.persons)`, puis le nombre de lignes de `organisations`, de `reste_a_classer` et de `pistes`. Ce sont les mêmes tables que le zip, donc les comptes ne peuvent pas diverger.
- La route du zip passe `datetime.now()` : c'est la date locale du serveur, comme `build_export_bundle` l'attend déjà. Elle renvoie `Response(data, media_type="application/zip", headers=_download_headers(name))`.
- La route du résumé renvoie `JSONResponse(service.export_summary(), headers={"Cache-Control": "no-store"})`.

- [ ] **Step 4 : vérifier le passage et la suite**

Run: `cd core && COLUMNS=200 uv run python -m pytest tests/api -q`, puis toute la suite, `uv run ruff format src tests`, `uv run ruff check src tests --ignore E501`, et `uv run --package geneweb-py mypy core/src/geneweb_py` depuis la racine.
Expected: tout vert, mypy 0 erreur.

- [ ] **Step 5 : commit**

```bash
git add core/src/geneweb_py/api/session_store.py core/src/geneweb_py/api/routers/sessions.py \
  core/src/geneweb_py/api/services/genealogy_service.py core/src/geneweb_py/api/routers/genealogy.py \
  core/tests/api/test_export_zip_route.py
git diff --cached --name-only
git commit -m "feat(exports): serve the export bundle and its summary from the API"
```

### Task 2 : onglet Export à bouton unique

**Files :**
- Modify: `core/src/geneweb_py/api/static/index.html` (`#panel-export`)
- Modify: `core/src/geneweb_py/api/static/app.js` (section `EXPORT`, `showTab`)
- Modify: `core/src/geneweb_py/api/static/app.css` (styles de `.export-orgs` / `.export-btns` à ajuster ou retirer s'ils ne servent plus)
- Test: `core/tests/api/test_static_frontend.py` (remplacer `test_export_tab_offers_organization_files`)

**Interfaces :**
- Consumes: les routes `/api/v1/genealogy/export/zip` et `/api/v1/genealogy/export/summary` de la Task 1, et les fonctions existantes `apiFetch`, `apiJson`, `syncIgnoredWords`.
- Produces: ids `btn-export-zip` et `export-summary` (plus `export-error`, conservé) ; fonctions JS `downloadZip()` et `loadExportSummary()`.

- [ ] **Step 1 : écrire le test qui échoue**

```python
def test_export_tab_offers_single_zip_download():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="btn-export-zip"' in html
    assert "Télécharger les données (.zip)" in html
    assert 'id="export-summary"' in html
    for old in ("btn-export-gedcom", "btn-export-json", "btn-export-xml",
                "btn-export-org-json", "btn-export-org-csv",
                "btn-export-org-links-csv", "btn-export-exp-csv"):
        assert old not in html and old not in js, old
    assert "EXPORT_FILENAMES" not in js
    assert "'/api/v1/genealogy/export/zip'" in js
    assert "'/api/v1/genealogy/export/summary'" in js
    assert "content-disposition" in js.lower()
    assert "#valider-et-enrichir" in html
    assert "Pistes étendues" not in html and "Pistes étendues" not in js
```

- [ ] **Step 2 : vérifier l'échec**

Run: `cd core && COLUMNS=200 uv run python -m pytest tests/api/test_static_frontend.py -q`
Expected: `test_export_tab_offers_single_zip_download` échoue, sur `btn-export-zip` absent.

- [ ] **Step 3 : implémenter**

**Panneau.** Dans l'ordre :
1. la phrase existante sur la génération à la volée ;
2. le bouton `<button class="btn-export" id="btn-export-zip">Télécharger les données (.zip)</button>` ;
3. `<p id="export-summary" class="text-muted" aria-live="polite"></p>` ;
4. un court paragraphe : l'archive regroupe les tableaux (CSV, JSON, SQLite), le fichier compagnon et un `LISEZMOI` ; le `.gw` n'est pas modifié ; lien vers `…/prosopo-gw#valider-et-enrichir` ;
5. `#export-error`.

La section `export-orgs` et ses quatre boutons disparaissent.

**Ligne de résumé.** Gabarit : `${fmtInt(personnes)} personnes · ${fmtInt(organisations)} organisations · ${fmtInt(a_classer)} événements à classer · ${fmtInt(pistes)} pistes`.
- Accord au singulier quand la valeur vaut 1 (« 1 personne », « 1 organisation », « 1 événement à classer », « 1 piste »).
- Pendant le chargement, la ligne affiche « Calcul du contenu… ». En cas d'erreur, la ligne est vide et le bouton reste actif.

**`loadExportSummary()`.** `showTab('export')` l'appelle. Elle attend `syncIgnoredWords()`, puis lit `apiJson('/api/v1/genealogy/export/summary')`. Elle recalcule à chaque affichage de l'onglet : les mots ignorés ou les données ont pu changer.

**`downloadZip()`.**
- Attend `syncIgnoredWords()`, puis appelle `apiFetch('/api/v1/genealogy/export/zip')`.
- Le bouton est `disabled` pendant la requête, avec le texte « Préparation de l'archive… », puis retrouve son libellé.
- Nom du fichier : `filename="…"` lu dans l'en-tête `Content-Disposition`, à défaut `prosopo-export.zip`.
- Téléchargement par blob, comme `downloadExport` aujourd'hui ; la gestion de `session-expired` et le message d'erreur sont conservés.
- `downloadExport`, `EXPORT_FILENAMES` et les sept écouteurs sont supprimés.

**CSS.** On retire seulement les règles devenues orphelines.

- [ ] **Step 4 : vérifier le passage et la suite**

Run: `cd core && COLUMNS=200 uv run python -m pytest tests/api -q`, puis toute la suite.
Expected: tout vert.

- [ ] **Step 5 : essai dans le navigateur (fixture synthétique)**

Lance l'API (`cd core && uv run python run_api.py`) et charge `core/tests/fixtures/simple_test.gw` dans l'onglet Export. Vérifie trois choses :
- la ligne de résumé s'affiche ;
- le clic télécharge `prosopo-simple_test-<date>.zip` ;
- l'onglet ne montre aucun autre bouton.

Le fichier téléchargé reste dans le dossier de téléchargement et n'est **jamais** copié dans le dépôt.

- [ ] **Step 6 : commit**

```bash
git add core/src/geneweb_py/api/static/index.html core/src/geneweb_py/api/static/app.js \
  core/src/geneweb_py/api/static/app.css core/tests/api/test_static_frontend.py
git diff --cached --name-only
git commit -m "feat(webapp): replace export buttons with a single zip download"
```

### Task 3 : README à jour

**Files :**
- Modify: `README.md` (l. 111, 232, 236 : passages qui décrivent les fichiers proposés par l'onglet Export)

**Interfaces :** aucune (documentation).

- [ ] **Step 1 : corriger les trois passages**

Un dépôt public ne doit pas décrire des boutons qui n'existent plus. Les trois passages disent désormais :
- l'onglet Export propose une archive unique, servie par `GET /api/v1/genealogy/export/zip` et nommée `prosopo-<base>-<AAAA-MM-JJ>.zip` ;
- les routes historiques (`/export/gedcom|json|xml|org-json|organizations-csv|organization-links-csv|shared-experiences-csv`) restent disponibles pour l'API ;
- `experiences_proches.csv` est dans l'archive.

Le reste du texte (format des CSV, ancres) ne change pas. Ne touche pas aux plans archivés de `core/docs/` ni de `core/doc/`.

- [ ] **Step 2 : vérifier**

Run: `rtk proxy grep -n "onglet Export" README.md`
Expected: aucun passage ne parle de boutons ou de fichiers séparés dans l'onglet Export.

- [ ] **Step 3 : commit**

```bash
git add README.md
git diff --cached --name-only
git commit -m "docs(exports): describe the single zip download of the Export tab"
```
