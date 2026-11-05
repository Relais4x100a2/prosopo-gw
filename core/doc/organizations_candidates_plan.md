# Organisations candidates (chantier A) : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Déduire des organisations candidates depuis les événements « Autre », les événements typés et les textes de profession, les exposer par l'API (liste, fiche, reste à classer, `.org.json` + 2 CSV) et dans un sixième onglet « Organisations » de la webapp.

**Architecture:** Le moteur (`core/event_to_organization.py`) produit organisations et liens dans `Genealogy` comme aujourd'hui, avec de nouvelles règles, des métadonnées (`named_from`, `trigger`) et une référence d'événement sur chaque lien. Un nouveau module de service (`api/services/organization_candidates.py`) calcule une fois par session un index de candidats (≥ 2 personnes) et le reste à classer ; un routeur `organizations` et trois routes d'export le servent ; la webapp statique (HTML/CSS/JS sans CDN) l'affiche.

**Tech Stack:** Python ≥ 3.11 (workspace `uv`), dataclasses, FastAPI + Pydantic, pytest, mypy strict, ruff ; front statique vanilla JS (CSP `default-src 'self'`).

**Spec:** `core/doc/organizations_candidates_design.md` (§ 3 à § 6 pour ce chantier ; § 7 pour le texte du README).

## Global Constraints

- Dépôt public : fixtures synthétiques uniquement (`DUPONT Jean`, `MARTIN Marie`…) ; jamais de nom, lieu ou date de vraie personne ; pas de `*.gw` réel.
- Git : `git add` chemins explicites, puis `git diff --cached --name-only` ; messages `type(scope): message` en anglais, un sujet par commit, terminés par `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` ; **jamais de `git push`** sans accord explicite de l'utilisateur.
- Qualité : mypy 0 erreur (`uv run mypy src/geneweb_py/` depuis `core/`), `uv run ruff check src tests --ignore E501` et `uv run ruff format --check src tests` propres, couverture `core` ≥ 80 %, tests verts à chaque tâche.
- Toutes les commandes se lancent depuis `core/` avec `uv run python -m pytest …` (suite complète : `COLUMNS=250 uv run python -m pytest -q`).
- Webapp : aucune ressource externe (CSP `default-src 'self'`), libellés en français, code et identifiants en anglais ; aucun `alert`/`confirm`.
- Les constantes du spec sont reprises telles quelles : `REVIEW_THRESHOLD = 0.7` inchangé ; confiances 0,8 / 0,7 / 0,5 ; seuil candidat = 2 personnes distinctes ; collectif = ≥ 3 témoins ; reste à classer : mots de plus de 3 lettres, 50 événements par groupe ; CSV UTF-8 avec BOM, séparateur `;`, en-têtes exacts de § 4 ; `Cache-Control: no-store` sur les exports.
- Le modèle `Organization` / `OrganizationLink` ne change pas de forme (seuls `metadata`, `notes`, `source_event_id` sont renseignés).

## Review Focus

1. Un tag « Autre » dont le reste n'est que des chiffres (`#Membre_1900`) ou un préfixe seul, avec un lieu sans complément : aucune proposition, et l'événement va au reste à classer (Tâche 1, test `test_tag_without_signal_is_ignored` conservé ; Tâche 3, test `test_unmatched_lists_other_events_without_candidate`).
2. Deux personnes portant la même profession textuelle sans employeur (« Instituteur » × 2) : aucun candidat (Tâche 1, `test_shared_plain_occupation_is_never_an_organization`).
3. Un lien chargé depuis un `.org.json` antérieur sans `source_event_id`, ou un `source_event_id` qui ne désigne plus un événement : l'index API ne lève pas, le membre est compté sans témoins et la source vaut `oth` (Tâche 3, `test_index_tolerates_links_without_event_reference`).
4. Un identifiant d'organisation contenant un caractère encodé dans l'URL (`#/organisation/ecole%20x`) et un identifiant inconnu : 404 propre côté API, message d'erreur dans le tiroir côté front sans casser la navigation (Tâche 3, `test_candidate_detail_unknown_id_is_404` ; Tâche 5, assertion sur `drawerError` dans `test_organizations_tab_*`).
5. Export CSV d'une session sans aucun candidat : fichier valide avec la seule ligne d'en-tête, BOM présent, HTTP 200 (Tâche 4, `test_csv_exports_without_candidates_have_header_only`).

---

## Carte des fichiers

| Fichier | Rôle |
|---|---|
| `core/src/geneweb_py/core/event_to_organization.py` (modifier) | Règles de déduction : vocabulaire, règles « Autre », `TYPED_EVENT_RULES`, texte de profession, `apply()` avec comptage des tags et référence d'événement |
| `core/tests/unit/test_event_to_organization.py` (modifier) | Tests du moteur |
| `core/src/geneweb_py/formats/org_sidecar.py` (modifier) | `sidecar_payload()` factorisé, filtrable par identifiants |
| `core/src/geneweb_py/api/services/organization_candidates.py` (créer) | Index des candidats, membres, reste à classer (dataclasses, pur Python) |
| `core/src/geneweb_py/api/services/organization_exports.py` (créer) | Rendu CSV des candidats et des liens, filtrage du `.org.json` |
| `core/src/geneweb_py/api/services/genealogy_service.py` (modifier) | Cache `get_candidate_index()` par session |
| `core/src/geneweb_py/api/models/organization.py` (créer) | Schémas Pydantic |
| `core/src/geneweb_py/api/routers/organizations.py` (créer) | `GET /candidates`, `GET /candidates/{id}`, `GET /unmatched` |
| `core/src/geneweb_py/api/routers/genealogy.py` (modifier) | `GET /export/org-json`, `/export/organizations-csv`, `/export/organization-links-csv` |
| `core/src/geneweb_py/api/main.py` (modifier) | Enregistrement du routeur |
| `core/tests/api/test_organizations_api.py` (créer) | Tests API (routeur + exports) |
| `core/src/geneweb_py/api/static/{index.html,app.js,style.css}` (modifier) | Onglet, fiche, reste à classer, exports, carte Stats |
| `core/tests/api/test_static_frontend.py` (modifier) | Tests textuels du front |
| `README.md`, `README.en.md`, `core/AGENTS.md` (modifier) | Documentation |

---

### Task 0: Versionner la conception et le plan

**Files:**
- Add: `core/doc/organizations_candidates_design.md`, `core/doc/organizations_candidates_plan.md`

- [ ] **Step 1: Vérifier qu'aucun nom réel ne figure dans les deux documents**

Run (depuis la racine) : `rtk proxy grep -n -i "DUPONT\|MARTIN" core/doc/organizations_candidates_design.md | head -3`
Expected: seuls des noms de fixtures synthétiques, ou rien. Les effectifs (454, 224, 7 053…) sont admis.

- [ ] **Step 2: Commit**

```bash
git add core/doc/organizations_candidates_design.md core/doc/organizations_candidates_plan.md
git diff --cached --name-only
git commit -m "docs(core): design and plan for organization candidates"
```

---

### Task 1: Moteur : vocabulaire, règles « Autre », événements typés, texte de profession

**Files:**
- Modify: `core/src/geneweb_py/core/event_to_organization.py`
- Test: `core/tests/unit/test_event_to_organization.py`

**Interfaces:**
- Consumes: `Event` (`event_type`, `event_type_raw`, `place_parts`, `notes`, `witnesses`, `date`), `Person.occupation`, `Organization.create(name, place=None, **kwargs)`, `Genealogy.link_person_to_organization(...)`.
- Produces (utilisés par la Tâche 3) :
  - `ESTABLISHMENT_WORDS: Dict[str, OrganizationType]` (clés repliées par `_fold`, liste de § 3.4 ; `"compagnie"` → `company`, le cas militaire est traité par `_establishment_in`).
  - `RELATION_WORDS: FrozenSet[str]` = {amitie, collaboration, correspondance, rencontre, voisinage}.
  - `OCCUPATION_PREPOSITIONS: Tuple[str, ...]` = `("à la", "à l'", "de la", "de l'", "chez", "pour", "aux", "des", "au", "du", "à")` (les plus longues d'abord).
  - `@dataclass(frozen=True) class TypedEventRule: type: OrganizationType; role: Optional[str]` (`role=None` pour `occu` : dérivé du texte).
  - `TYPED_EVENT_RULES: Dict[EventType, TypedEventRule]` : table de § 3.6.
  - `OrganizationProposal` gagne `named_from: Optional[str] = None`, `trigger: Optional[str] = None`, `relation: bool = False`.
  - `EventToOrganizationMapper.propose(self, event: Event, tag_person_counts: Optional[Mapping[str, int]] = None, person_occupation: Optional[str] = None) -> Optional[OrganizationProposal]`.
  - `EventToOrganizationMapper.propose_from_occupation(self, text: str, place: Optional[str] = None) -> Optional[OrganizationProposal]`.
  - `event_ref(person_id: str, index: int) -> str` = `f"pevt:{person_id}:{index}"` ; `parse_event_ref(ref: Optional[str]) -> Optional[Tuple[str, int]]` (None si format inattendu). Posé dans `OrganizationLink.source_event_id` par `apply()` ; `"occu_attr"` dans `source_event_type` pour l'attribut profession, sans référence.
  - `Organization.metadata["named_from"] ∈ {"tag","place","typed_event","occupation_text"}`, `metadata["trigger"]` (mot replié ou None), `metadata["to_determine"]` (bool, cas 3 de § 3.2), `metadata["complement"]` ou `metadata["tag"]` (source écartée, si elle existe), `"relation"` dans `Organization.notes`. Les alias ne reçoivent jamais la source écartée.
  - `OrganizationProposal` gagne aussi `to_determine: bool = False` et `extra: Dict[str, str]` (copié dans `metadata` : `complement` / `tag`).

- [ ] **Step 1: Adapter les tests existants aux nouvelles priorités (§ 3.2 : complément à mot d'établissement > tag qui dit plus qu'un rôle > « à déterminer »)**

`test_place_complement_becomes_organization` garde son résultat (« atelier » est un mot d'établissement, le complément l'emporte) : ajouter `org.type is OrganizationType.COMPANY`, `org.confidence == 0.8`, `org.metadata["named_from"] == "place"`, `org.metadata["trigger"] == "atelier"`, `org.metadata["tag"] == "peinture"` (reste du tag, replié), `org.aliases == []`, lien `source_event_id == "pevt:DUPONT_Jean_0:0"`. Puis :

```python
def test_tag_wins_over_complement_without_establishment_word(self):
    g = _parse("#Membre_Academie 1900 #p [Salle_Rameau]_-_Lyon")
    g.infer_organizations()
    org = g.get_organization("academie_lyon")
    assert org.name == "Academie" and org.metadata["named_from"] == "tag"
    assert org.metadata["complement"] == "Salle Rameau" and org.aliases == []
    assert org.type is OrganizationType.SCHOOL      # mot d'établissement « académie » dans le tag

def test_role_only_tag_with_plain_complement_is_to_determine(self):
    g = _parse("#Membre 1890 #p [Les_Amis_du_Vieux_Lyon]_-_Lyon")
    g.infer_organizations()
    org = g.get_organization("les_amis_du_vieux_lyon_lyon")
    assert org.name == "Les Amis du Vieux Lyon" and org.metadata["to_determine"] is True
    assert org.needs_review is True and org.confidence == 0.5
    assert org.type is OrganizationType.ASSOCIATION  # règle « membre »
```

Les tests existants qui supposaient « complément seul → 0,7 sans revue » passent au cas « à déterminer » (0,5, `needs_review`) : adapter leurs assertions, pas le moteur.

- [ ] **Step 2: Écrire les tests des règles « Autre »**

```python
class TestOtherEventRules:
    def test_establishment_word_in_complement_sets_type_and_trigger(self):
        g = _parse("#Reunion 1900 #p [Usine_Martin]_-_Roubaix")
        g.infer_organizations()
        org = g.get_organization("usine_martin_roubaix")
        assert org.type is OrganizationType.COMPANY and org.confidence == 0.8
        assert org.metadata["named_from"] == "place" and org.metadata["trigger"] == "usine"
        assert org.metadata["tag"] == "Reunion" and org.metadata["to_determine"] is False

    def test_tag_without_prefix_needs_two_persons(self):
        one = _parse("#Cercle_Philatelique 1900")
        assert one.infer_organizations() == (0, 0)
        two = _parse_two("#Cercle_Philatelique 1900", "#Cercle_Philatelique 1905")
        assert two.infer_organizations() == (1, 2)
        org = two.get_organization("cercle_philatelique")
        assert org.confidence == 0.5 and org.needs_review is True
        assert org.type is OrganizationType.ASSOCIATION and org.metadata["trigger"] == "cercle"

    def test_relation_word_marks_a_circle(self):
        g = _parse_two("#Amitie_Peintres 1900", "#Amitie_Peintres 1901")
        g.infer_organizations()
        org = g.get_organization("peintres")  # ou "amitie_peintres" : fixer la forme, voir note
        assert org.type is OrganizationType.OTHER and org.needs_review is True
        assert "relation" in org.notes and org.metadata["trigger"] == "amitie"

    def test_compagnie_followed_by_number_is_military(self):
        g = _parse("#Membre 1914 #p [Compagnie_3]_-_Lille")
        g.infer_organizations()
        assert g.get_organization("compagnie_3_lille").type is OrganizationType.MILITARY
```

`_parse_two(body_a, body_b)` : fabrique un `.gw` avec `pevt DUPONT Jean` et `pevt MARTIN Marie` (même motif que `_parse`). Note sur le nom d'un tag de relation : le tag entier est le nom (`Amitie Peintres`, id `amitie_peintres`) puisqu'il n'a pas de préfixe de rôle ; corriger l'assertion en conséquence.

- [ ] **Step 3: Écrire les tests des événements typés et du texte de profession**

```python
class TestTypedEvents:
    def test_occupation_event_with_complement_creates_company(self):
        g = _parse("#occu 1895 #p [Usine_Martin]_-_Roubaix\nnote Contremaître")
        assert g.infer_organizations() == (1, 1)
        org = g.get_organization("usine_martin_roubaix")
        link = g.get_organization_links(organization_id=org.id)[0]
        assert org.type is OrganizationType.COMPANY and org.confidence == 0.8
        assert org.metadata["named_from"] == "typed_event"
        assert link.role == "Contremaître" and link.source_event_type == "occu"
        assert link.start_date.sort_year() == 1895

    def test_establishment_word_overrides_default_type(self):
        g = _parse("#occu 1895 #p [Lycée_Pasteur]_-_Lille")
        g.infer_organizations()
        assert g.get_organization("lycee_pasteur_lille").type is OrganizationType.SCHOOL

    def test_each_typed_event_gets_its_role(self):
        cases = {"educ": "élève", "grad": "diplômé", "degr": "diplômé", "adhe": "membre",
                 "hosp": "patient", "mser": "soldat", "demm": "soldat", "elec": "élu", "ordn": "ordonné"}
        for code, role in cases.items():
            g = _parse(f"#{code} 1900 #p [Maison_X]_-_Lyon")
            g.infer_organizations()
            assert g.organization_links[0].role == role, code

    def test_residence_and_census_never_match(self):
        g = _parse("#resi 1900 #p [Maison_X]_-_Lyon\n#cens 1901 #p [Usine_Y]_-_Lyon")
        assert g.infer_organizations() == (0, 0)

    def test_typed_event_without_complement_gives_nothing(self):
        assert _parse("#educ 1900 #p Lyon").infer_organizations() == (0, 0)


class TestOccupationText:
    def test_attribute_with_establishment_word(self):
        g = _parse_attr("Comptable_à_la_Banque_Durand")
        assert g.infer_organizations() == (1, 1)
        org = g.get_organization("banque_durand")
        link = g.organization_links[0]
        assert org.type is OrganizationType.COMPANY and org.confidence == 0.7
        assert org.metadata["named_from"] == "occupation_text" and org.metadata["trigger"] == "banque"
        assert link.role == "Comptable" and link.source_event_type == "occu_attr"
        assert link.source_event_id is None and link.start_date is None

    def test_chez_without_establishment_word_needs_review(self):
        g = _parse_attr("Ouvrier_chez_Durand")
        g.infer_organizations()
        org = g.get_organization("durand")
        assert org.confidence == 0.5 and org.needs_review is True

    def test_plain_or_village_occupation_gives_nothing(self):
        for text in ("Instituteur", "Cultivateur_à_Saint-Pierre", "Employé_de_commerce"):
            assert _parse_attr(text).infer_organizations() == (0, 0), text

    def test_only_first_comma_part_is_read(self):
        g = _parse_attr("Instituteur,_puis_directeur_de_l'École_Normale")
        assert g.infer_organizations() == (0, 0)

    def test_occupation_event_note_without_complement_uses_city(self):
        g = _parse("#occu 1895 #p Roubaix\nnote Tisseur à l'Usine Martin")
        g.infer_organizations()
        org = g.get_organization("usine_martin_roubaix")
        assert org.place == "Roubaix" and g.organization_links[0].source_event_type == "occu"

    def test_shared_plain_occupation_is_never_an_organization(self):
        g = _parse_two_attrs("Instituteur", "Instituteur")
        assert g.infer_organizations() == (0, 0)
```

`_parse_attr(occupation)` : `.gw` avec `fam DUPONT Jean #occu {occupation} + MARTIN Marie` (le parser pose `Person.occupation`, vérifié sur ce motif) ; `_parse_two_attrs(a, b)` pose `#occu` sur les deux conjoints.

- [ ] **Step 4: Écrire les tests de fusion et d'idempotence**

```python
class TestMerge:
    def test_typed_event_and_other_event_merge_on_same_organization(self):
        g = _parse_two("#occu 1895 #p [Usine_Martin]_-_Roubaix", "#Reunion 1900 #p [Usine_Martin]_-_Roubaix")
        assert g.infer_organizations() == (1, 2)
        org = g.get_organization("usine_martin_roubaix")
        assert org.metadata["named_from"] == "typed_event"   # première création conservée
        assert sorted(l.source_event_type for l in g.organization_links) == ["Reunion", "occu"]

    def test_merge_keeps_best_confidence_and_clears_review_when_one_source_is_sure(self):
        ...  # 0.5 (tag partagé) puis 0.8 (typé) → confidence 0.8, needs_review False

    def test_two_events_of_one_person_give_two_links(self):
        g = _parse("#Membre_Academie 1900\n#Membre_Academie 1910")
        assert g.infer_organizations() == (1, 2)
        assert [l.source_event_id for l in g.organization_links] == ["pevt:DUPONT_Jean_0:0", "pevt:DUPONT_Jean_0:1"]
```

`test_inference_is_idempotent` existant reste tel quel.

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/unit/test_event_to_organization.py -q`
Expected: FAIL (`AttributeError`/`TypeError` sur les nouveaux noms, assertions des priorités).

- [ ] **Step 6: Implémenter le vocabulaire et les aides**

Dans `event_to_organization.py` : les constantes de l'interface ; `_words(text: str) -> List[str]` (découpe sur `_`, `-`, espaces, apostrophes, repli par `_fold`) ; `_establishment_in(text: str) -> Optional[Tuple[str, OrganizationType]]` (premier mot d'établissement ; `compagnie` suivi d'un mot numérique → `MILITARY`) ; `_relation_in(text: str) -> Optional[str]` ; `event_ref` / `parse_event_ref`.

- [ ] **Step 7: Implémenter `propose()` selon § 3.2-3.3 et § 3.6**

Ordre : si `event.event_type in TYPED_EVENT_RULES` → branche typée (complément obligatoire ; rôle = `rule.role` ou, pour `occu`, `event.notes[0]` sinon `person_occupation` sinon `"employé"` ; type = mot d'établissement sinon `rule.type` ; confiance 0,8 ; `named_from="typed_event"`). Sinon si `OTHER`, `rule, tag_name = _split_tag(...)`, puis dans cet ordre :
1. complément contenant un mot d'établissement → nom = complément, type du mot, 0,8, `named_from="place"`, `extra["tag"] = tag_name` s'il existe ;
2. `tag_name` (reste du tag, ou tag entier sans préfixe) → nom = `tag_name`, `named_from="tag"`, `extra["complement"]` = complément s'il existe ; avec règle → 0,8, type = mot d'établissement du tag sinon `rule.type` ; sans règle, exige `tag_person_counts.get(_fold(tag_name), 0) >= 2` → 0,5, type du mot d'établissement ou `OTHER` ; mot de relation → `OTHER`, `relation=True`, `notes=["relation"]` (même seuil) ; si le seuil n'est pas atteint, passer au cas 3 ;
3. complément restant → nom = complément, `named_from="place"`, `to_determine=True`, 0,5, type = `rule.type` sinon `OTHER` ;
4. sinon `None`.
`place` = ville ; `role` = `rule.role` si règle. `trigger` = mot d'établissement ou de relation trouvé, sinon `None`. La branche typée et le texte de profession ne connaissent pas le cas « à déterminer ».

- [ ] **Step 8: Implémenter `propose_from_occupation()` selon § 3.7**

Texte → espaces à la place de `_` → partie avant la première virgule → recherche de la première préposition de `OCCUPATION_PREPOSITIONS` entourée d'espaces (repli pour la comparaison, découpe sur l'original) → `role` = avant, `x` = après (strip). Retenu si `_establishment_in(x)` (confiance 0,7, type du mot) ou préposition `chez` (0,5, `COMPANY`). `named_from="occupation_text"`, `place=place`.

- [ ] **Step 9: Réécrire `apply()`**

Pré-passe : `tag_person_counts` = nombre de personnes distinctes par `_fold(tag_name)` sur les événements `OTHER`. Puis pour chaque personne et chaque `(index, event)` : `proposal = self._refine(person_id, event, self.propose(event, tag_person_counts, person.occupation))` ; si `None` et l'événement est un `occu` sans complément avec une note : `self.propose_from_occupation(event.notes[0], city)`. Après les événements : si `person.occupation` : `propose_from_occupation(person.occupation)` avec `source_event_type="occu_attr"`, `start_date=None`, `source_event_id=None`. Création : `Organization.create(name, place=, type=, aliases=, notes=, confidence=, needs_review=proposal.review_required, metadata={"named_from": ..., "trigger": ..., "to_determine": ..., **proposal.extra})` ; fusion si l'id existe : `confidence = max`, `needs_review = existing.needs_review and proposal.review_required`, `to_determine = existing and proposal` (une source sûre lève le doute), notes unies, autres métadonnées inchangées. Clé de dédoublonnage : la clé actuelle + `source_event_id`.

- [ ] **Step 10: Lancer tests, mypy et ruff**

Run: `uv run python -m pytest tests/unit/test_event_to_organization.py tests/unit/test_organization.py -q && uv run mypy src/geneweb_py/ && uv run ruff check src tests --ignore E501 && uv run ruff format src tests`
Expected: tous PASS, `Success: no issues found`.

- [ ] **Step 11: Vérifier sur la base réelle locale (effectifs seulement, rien n'est versionné)**

Run: `uv run python -I /tmp/claude-1000/-home-guillaumecayeux-code-dev-TOLDOT-prosopo-gw/6ec011e2-fec3-4f28-b3d2-5c3dc5c06f2e/scratchpad/orgs.py /home/guillaumecayeux/Téléchargements/base.gw` (adapter le script pour n'imprimer que : organisations créées, dont ≥ 2 personnes, répartition par `named_from`).
Expected: des effectifs plausibles (ordre de grandeur : quelques dizaines de candidats), aucune exception.

- [ ] **Step 12: Commit**

```bash
git add src/geneweb_py/core/event_to_organization.py tests/unit/test_event_to_organization.py
git diff --cached --name-only
git commit -m "feat(core): organization candidates from tags, typed events and occupations"
```

---

### Task 2: Fichier compagnon filtrable

**Files:**
- Modify: `core/src/geneweb_py/formats/org_sidecar.py`
- Test: `core/tests/unit/test_organization.py`

**Interfaces:**
- Produces: `sidecar_payload(genealogy: Genealogy, organization_ids: Optional[Collection[str]] = None) -> Dict[str, Any]` renvoyant `{"version": SIDECAR_VERSION, "organizations": [...], "links": [...]}` ; avec un filtre, seules les organisations listées et leurs liens. `export_organizations()` l'appelle.

- [ ] **Step 1: Écrire le test**

```python
def test_sidecar_payload_can_be_restricted_to_some_organizations(self):
    # deux organisations, une seule retenue
    payload = sidecar_payload(genealogy, {"usine_martin_roubaix"})
    assert [o["id"] for o in payload["organizations"]] == ["usine_martin_roubaix"]
    assert {l["organization_id"] for l in payload["links"]} == {"usine_martin_roubaix"}
    assert payload["version"] == SIDECAR_VERSION
```

- [ ] **Step 2: Vérifier l'échec, implémenter, vérifier le succès**

Run: `uv run python -m pytest tests/unit/test_organization.py -q` → FAIL (`ImportError`) puis PASS. L'export existant doit produire exactement le même fichier qu'avant (le test d'aller-retour existant le garantit).

- [ ] **Step 3: Commit**

```bash
git add src/geneweb_py/formats/org_sidecar.py tests/unit/test_organization.py
git commit -m "feat(formats): sidecar payload restricted to given organizations"
```

---

### Task 3: Index des candidats, schémas et routeur `organizations`

**Files:**
- Create: `core/src/geneweb_py/api/services/organization_candidates.py`
- Create: `core/src/geneweb_py/api/models/organization.py`
- Create: `core/src/geneweb_py/api/routers/organizations.py`
- Modify: `core/src/geneweb_py/api/services/genealogy_service.py` (`__init__` l.88-96, remises à zéro de `_witness_index` l.648, 694, 801, 831-861)
- Modify: `core/src/geneweb_py/api/main.py:152-176`
- Test: `core/tests/api/test_organizations_api.py`

**Interfaces:**
- Consumes: Tâche 1 (`parse_event_ref`, `metadata`, `notes`, `source_event_type`), `GenealogyService.genealogy`, `get_session_service`, `PaginatedResponse`/`PaginationInfo(page, size, total, pages, has_next, has_prev)`, `SuccessResponse`.
- Produces, dans `organization_candidates.py` :
  - `COLLECTIVE_MIN_WITNESSES = 3`, `CANDIDATE_MIN_PERSONS = 2`, `UNMATCHED_MIN_WORD_LEN = 4`, `UNMATCHED_GROUP_CAP = 50`.
  - `@dataclass class CandidateMember: person_id, person_name, role, date (Optional[str], display_text), place, source_event_type (valeur API : "oth", "occu", "educ", "occu_attr"…), event_type_raw (Optional[str]), event_label (tag lisible pour un « Autre », métier pour une profession, sinon ""), witness_count: int, year: Optional[int]`.
  - `@dataclass class Candidate: id, name, type (str, valeur de l'enum), place, named_from, sources: List[str], trigger, confidence: Optional[float], needs_review: bool, to_determine: bool, relation: bool, collective: bool, person_count, event_count, first_year, last_year, places: List[str], roles: List[str], members: List[CandidateMember]`.
  - `@dataclass class UnmatchedEvent: person_id, person_name, event_type_raw, label, date, place` ; `@dataclass class UnmatchedGroup: word, count, events` ; `@dataclass class CandidateIndex: candidates: Dict[str, Candidate]; unmatched_total: int; unmatched_groups: List[UnmatchedGroup]`.
  - `build_candidate_index(genealogy: Genealogy) -> CandidateIndex` : appelle `genealogy.infer_organizations()` si `genealogy.organizations` est vide, puis calcule.
  - `person_display_name(person: Person) -> str` = `"{last_name} {first_name}"` avec `_` → espace (et `.n` si `occurrence_number > 0`).
  - `sort_candidates(candidates: Iterable[Candidate], sort: str) -> List[Candidate]` : `persons` = `person_count` desc puis nom ; `period` = `first_year` asc (None en dernier) ; `name` = nom replié.
  - `filter_candidates(candidates, type_=None, named_from=None, q=None) -> List[Candidate]` (`q` : sous-chaîne repliée sur `name`).
- Produces, dans `genealogy_service.py` : `GenealogyService.get_candidate_index(self) -> CandidateIndex` (cache `self._candidate_index: Optional[CandidateIndex]`, remis à `None` à chaque endroit où `_witness_index` l'est).
- Produces, dans `models/organization.py` : `OrganizationCandidateSchema` (champs de `Candidate` sauf `members`), `OrganizationMemberSchema`, `OrganizationCandidateDetailSchema(OrganizationCandidateSchema)` + `members`, `UnmatchedEventSchema`, `UnmatchedGroupSchema`, `UnmatchedResponseSchema(total: int, groups: List[UnmatchedGroupSchema])`.
- Produces, routes (préfixe `/api/v1/organizations`, tag `organizations`) : `GET /candidates?page=1&size=20&sort=persons&type=&named_from=&q=` → `PaginatedResponse` ; `GET /candidates/{organization_id}` → `OrganizationCandidateDetailSchema` ou 404 ; `GET /unmatched` → `UnmatchedResponseSchema`.

- [ ] **Step 1: Écrire la fixture et les tests API**

Fixture module (chaîne `GW` synthétique, à l'image de `tests/api/test_event_custom_type.py`) : DUPONT Jean (`#occu 1895 #p [Usine_Martin]_-_Roubaix` avec 3 témoins et note `Contremaître`, `#Cercle_Philatelique 1900`, `#Membre_1900 1900`), MARTIN Marie (`#Reunion 1902 #p [Usine_Martin]_-_Roubaix`, `#Cercle_Philatelique 1905`), DURAND Paul (`#Capitaine_de_navire 1890`, `#Conference_Histoire 1911`), MARTIN Pierre (`#Conference_Histoire 1912`), tous avec un `#Comite_des_fetes 1920` pour une seule personne (reste à classer). Montage : `service = GenealogyService(GeneWebParser().parse_string(GW)); app.dependency_overrides[get_session_service] = lambda: service` dans une fixture pytest `client` qui fait `app.dependency_overrides.clear()` en sortie.

```python
def test_candidates_default_sort_by_persons(client):
    data = client.get("/api/v1/organizations/candidates").json()
    ids = [c["id"] for c in data["items"]]
    assert ids[0] == "usine_martin_roubaix"
    assert "comite_des_fetes" not in ids           # une seule personne
    first = data["items"][0]
    assert first["collective"] is True and first["person_count"] == 2 and first["event_count"] == 2
    assert first["first_year"] == 1895 and first["last_year"] == 1902
    assert first["sources"] == ["occu", "oth"] and first["named_from"] == "typed_event"
    assert data["pagination"]["total"] == len(ids)

def test_candidates_filters_and_sorts(client):
    assert all(c["type"] == "association" for c in client.get("/api/v1/organizations/candidates?type=association").json()["items"])
    names = [c["name"] for c in client.get("/api/v1/organizations/candidates?sort=name").json()["items"]]
    assert names == sorted(names, key=str.casefold)
    assert client.get("/api/v1/organizations/candidates?q=philat").json()["pagination"]["total"] == 1
    assert client.get("/api/v1/organizations/candidates?sort=bogus").status_code == 422

def test_candidate_detail_lists_members(client):
    d = client.get("/api/v1/organizations/candidates/usine_martin_roubaix").json()
    m = next(x for x in d["members"] if x["person_id"] == "DUPONT_Jean_0")
    assert m == {"person_id": "DUPONT_Jean_0", "person_name": "DUPONT Jean", "role": "Contremaître",
                 "date": "1895", "place": "[Usine_Martin]_-_Roubaix", "source_event_type": "occu",
                 "event_type_raw": "occu", "event_label": "Contremaître", "witness_count": 3, "year": 1895}

def test_candidate_detail_unknown_id_is_404(client):
    assert client.get("/api/v1/organizations/candidates/nope").status_code == 404
    assert client.get("/api/v1/organizations/candidates/ecole%20x").status_code == 404

def test_unmatched_lists_other_events_without_candidate(client):
    u = client.get("/api/v1/organizations/unmatched").json()
    words = {g["word"]: g["count"] for g in u["groups"]}
    assert words["fetes"] == 4 and words["comite"] == 4      # 4 personnes, 1 chacune : groupes par mot
    assert u["groups"][-1]["word"] == "autres"               # Membre_1900, Capitaine_de_navire
    assert all(len(g["events"]) <= 50 for g in u["groups"])
    assert u["total"] == 6

def test_index_is_computed_once_per_service(monkeypatch): ...  # compteur sur build_candidate_index

def test_index_tolerates_links_without_event_reference():
    g = GeneWebParser().parse_string(GW); g.infer_organizations()
    for link in g.organization_links: link.source_event_id = "pevt:ghost:9"
    idx = build_candidate_index(g)
    assert idx.candidates["usine_martin_roubaix"].sources == ["oth"]
    assert all(m.witness_count == 0 for m in idx.candidates["usine_martin_roubaix"].members)

def test_requires_session_token():
    with TestClient(app) as c: assert c.get("/api/v1/organizations/candidates").status_code in (401, 403)
```

Ajuster les valeurs attendues (`total`, listes) après la première exécution **seulement** si l'écart vient d'une règle du spec mal comptée dans ce plan, jamais pour masquer un bug ; noter la correction dans le message de commit.

- [ ] **Step 2: Vérifier l'échec**

Run: `uv run python -m pytest tests/api/test_organizations_api.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implémenter `organization_candidates.py`**

Membres : pour chaque lien, événement résolu par `parse_event_ref(link.source_event_id)` dans `genealogy.persons[pid].events[idx]` (tolérant) ; `source_event_type` = `"occu_attr"` si tel, sinon `event.event_type.value` si résolu, sinon `"oth"`. Agrégats par organisation ; candidat si `len({m.person_id}) >= CANDIDATE_MIN_PERSONS` ; `relation` = `"relation" in org.notes`. Reste à classer : événements `OTHER` de toutes les personnes dont aucun lien (résolu par référence) ne mène à un candidat ; mots = `_words(tag)` de longueur ≥ 4 ; groupes pour les mots comptés ≥ 2, triés par effectif puis mot ; groupe final `"autres"` pour les événements sans mot retenu (omis s'il est vide).

- [ ] **Step 4: Implémenter schémas, cache de service, routeur, enregistrement**

Routeur : `sort: Literal["persons", "period", "name"] = Query("persons")`, `size: int = Query(20, ge=1, le=100)` ; 404 via `HTTPException(404, detail="Organisation inconnue")`. Enregistrer avec `app.include_router(organizations.router, prefix="/api/v1/organizations", tags=["organizations"])` à la suite d'`events` dans `main.py`. Schémas construits avec `Model.model_validate(dataclasses.asdict(obj))`.

- [ ] **Step 5: Vérifier, qualité, suite complète**

Run: `uv run python -m pytest tests/api -q && uv run mypy src/geneweb_py/ && uv run ruff check src tests --ignore E501 && uv run ruff format src tests`
Expected: PASS, 0 erreur mypy.

- [ ] **Step 6: Commit**

```bash
git add src/geneweb_py/api/services/organization_candidates.py src/geneweb_py/api/models/organization.py src/geneweb_py/api/routers/organizations.py src/geneweb_py/api/services/genealogy_service.py src/geneweb_py/api/main.py tests/api/test_organizations_api.py
git diff --cached --name-only
git commit -m "feat(api): organization candidates endpoints with unmatched events"
```

---

### Task 4: Exports `.org.json` et CSV

**Files:**
- Create: `core/src/geneweb_py/api/services/organization_exports.py`
- Modify: `core/src/geneweb_py/api/routers/genealogy.py` (à côté de `export_genealogy`, l.65-100)
- Test: `core/tests/api/test_organizations_api.py`

**Interfaces:**
- Consumes: `CandidateIndex` (Tâche 3), `sidecar_payload` (Tâche 2), `limiter`, `Request`.
- Produces: `CANDIDATES_CSV_HEADER: List[str]` (16 colonnes de § 4), `LINKS_CSV_HEADER: List[str]` (12 colonnes) ; `candidates_csv(index: CandidateIndex) -> str` ; `links_csv(index: CandidateIndex) -> str` (une ligne par membre de candidat, `statut` et `nom_retenu` vides) ; `candidates_sidecar(genealogy: Genealogy, index: CandidateIndex) -> Dict[str, Any]`. Les deux CSV commencent par `﻿`, séparateur `;`, `csv.writer(..., delimiter=";", lineterminator="\n")`, listes jointes par `|`, booléens `oui`/`non`, confiance au format `0.8`.
- Routes (avant `/export/{format}` pour que le chemin littéral gagne) : `GET /api/v1/genealogy/export/org-json` → `application/json`, `Content-Disposition: attachment; filename="genealogie.org.json"` ; `GET …/export/organizations-csv` → `text/csv; charset=utf-8`, `organisations.csv` ; `GET …/export/organization-links-csv` → `liens_organisations.csv`. `@limiter.limit("40/minute")`, `request: Request`, `Cache-Control: no-store`.

- [ ] **Step 1: Écrire les tests**

```python
def test_org_json_export_contains_only_candidates(client):
    r = client.get("/api/v1/genealogy/export/org-json")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert 'filename="genealogie.org.json"' in r.headers["content-disposition"]
    body = r.json()
    assert body["version"] == 1
    assert "comite_des_fetes" not in {o["id"] for o in body["organizations"]}
    assert {l["organization_id"] for l in body["links"]} <= {o["id"] for o in body["organizations"]}

def test_candidates_csv_header_and_rows(client):
    r = client.get("/api/v1/genealogy/export/organizations-csv")
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    assert rows[0] == "id;nom;type;lieu;source_du_nom;sources;mot_declencheur;confiance;a_revoir;collectif;nb_personnes;nb_evenements;premiere_annee;derniere_annee;lieux;roles".split(";")
    usine = next(r for r in rows if r[0] == "usine_martin_roubaix")
    assert usine[1] == "Usine Martin" and usine[9] == "oui" and usine[10] == "2"
    assert 'filename="organisations.csv"' in r.headers["content-disposition"]

def test_links_csv_header_and_readable_names(client):
    rows = ...  # même lecture
    assert rows[0] == "organisation_id;organisation;personne_id;personne;role;date;lieu;type_evenement;evenement;nb_temoins;statut;nom_retenu".split(";")
    row = next(r for r in rows if r[2] == "DUPONT_Jean_0" and r[0] == "usine_martin_roubaix")
    assert row[3] == "DUPONT Jean" and row[7] == "occu" and row[8] == "Contremaître" and row[9] == "3"
    assert row[10] == "" and row[11] == ""
    cercle = next(r for r in rows if r[0] == "cercle_philatelique")
    assert cercle[8] == "Cercle Philatelique"      # tag lisible

def test_csv_exports_without_candidates_have_header_only():
    service = GenealogyService(GeneWebParser().parse_string(EMPTY_GW))  # une personne, aucun événement
    ... ; assert rows == [CANDIDATES_CSV_HEADER] ; status 200 ; BOM présent

def test_unknown_export_format_still_404_or_422(client):
    assert client.get("/api/v1/genealogy/export/org-xml").status_code in (404, 422)
```

- [ ] **Step 2: Vérifier l'échec, implémenter, vérifier le succès**

Run: `uv run python -m pytest tests/api/test_organizations_api.py -q` → FAIL puis PASS. Puis `uv run mypy src/geneweb_py/ && uv run ruff check src tests --ignore E501 && uv run ruff format src tests`.

- [ ] **Step 3: Commit**

```bash
git add src/geneweb_py/api/services/organization_exports.py src/geneweb_py/api/routers/genealogy.py tests/api/test_organizations_api.py
git commit -m "feat(api): export organization candidates as org.json and CSV"
```

---

### Task 5: Webapp : onglet « Organisations », fiche, reste à classer, exports, Stats

**Files:**
- Modify: `core/src/geneweb_py/api/static/index.html` (onglets l.73-79, panneaux l.163-179)
- Modify: `core/src/geneweb_py/api/static/app.js` (`init` l.169, `ROUTE_TABS`/`TAB_ROUTES` l.407-414, `parseRoute` l.416, `applyRoute` l.522, `renderStats` l.1661, `EXPORT_EXT`/`downloadExport`/`wireExportTab` l.1792-1824)
- Modify: `core/src/geneweb_py/api/static/style.css`
- Test: `core/tests/api/test_static_frontend.py`

**Interfaces:**
- Consumes: routes de la Tâche 3 et 4 ; `showInDrawer(content, kind, id, crumb)`, `drawerShows`, `setDrawerLoading`, `drawerError`, `navigate`, `escHtml`, `formatGwName`, `personHash`, `apiJson`, `barCard`/`stat-card`.
- Produces (identifiants HTML) : onglet `tab-organizations` (`data-tab="organizations"`, libellé « Organisations », placé entre Événements et Stats), panneau `panel-organizations` contenant : `<p class="orgs-intro">`, barre `orgs-bar` avec `orgs-sort` (select : `persons` « Personnes », `period` « Période », `name` « Nom »), `orgs-type` (select, option vide « Tous les types » + libellés `ORG_TYPE_LABELS`), `orgs-source` (select : « Toutes les sources », `tag` « Nom personnalisé », `place` « Lieu », `typed_event` « Événement typé », `occupation_text` « Profession »), `orgs-search` (`type="search"`), `orgs-clear-btn` ; `orgs-list`, `orgs-prev`, `orgs-page-info`, `orgs-next` ; `<details id="orgs-unmatched">` avec `<summary id="orgs-unmatched-summary">` et `orgs-unmatched-body`. Export : bloc `<section class="export-orgs">` avec titre « Organisations candidates », paragraphe (fichier compagnon, `.gw` intact, lien `<a href="https://github.com/Relais4x100a2/prosopo-gw#valider-et-enrichir" target="_blank" rel="noopener">`), boutons `btn-export-org-json`, `btn-export-org-csv`, `btn-export-org-links-csv`.
- Produces (JS) : `state.organizations = { items: [], page: 1, pages: 1, total: 0, sort: 'persons', type: '', named_from: '', q: '' }` ; `ROUTE_TABS.organisations = 'organizations'`, `ROUTE_TABS.organisation = 'organizations'`, `TAB_ROUTES.organizations = 'organisations'` ; `parseRoute` accepte un id pour `organisation` ; `organizationsListHash(page, filters)`, `organizationHash(id)` ; `wireOrganizationsTab()`, `applyOrganizationsRoute(params)`, `loadOrganizations()`, `renderOrganizations()`, `openOrganizationDetail(id)`, `buildOrganizationPanel(org)`, `loadUnmatched()`, `renderUnmatched(data)` ; constantes `ORG_TYPE_LABELS` (company « Entreprise », school « École », association « Association », institution « Institution », religious « Religieux », military « Militaire », other « Autre »), `NAMED_FROM_LABELS`, `SOURCE_LABELS` (`oth` « événement libre », `occu` « profession », `educ` « éducation », `grad`/`degr` « diplôme », `adhe` « adhésion », `hosp` « hospitalisation », `mser`/`demm` « service militaire », `elec` « élection », `ordn` « ordination », `occu_attr` « profession (attribut) ») ; `EXPORT_FILENAMES = { gedcom: 'genealogie.ged', json: 'genealogie.json', xml: 'genealogie.xml', 'org-json': 'genealogie.org.json', 'organizations-csv': 'organisations.csv', 'organization-links-csv': 'liens_organisations.csv' }` remplace `EXPORT_EXT`.

- [ ] **Step 1: Mettre à jour le test des onglets et écrire les tests du front**

Dans `test_tabs_are_keyboard_accessible_buttons`, remplacer les trois `5` par `6`. Ajouter :

```python
def test_organizations_tab_routes_list_and_detail():
    html, js = ...
    assert 'id="tab-organizations"' in html and 'id="panel-organizations"' in html
    assert html.index('id="tab-events"') < html.index('id="tab-organizations"') < html.index('id="tab-stats"')
    for i in ("orgs-sort", "orgs-type", "orgs-source", "orgs-search", "orgs-list", "orgs-unmatched", "orgs-unmatched-body"):
        assert f'id="{i}"' in html, i
    assert "organisations: 'organizations'" in js and "organisation: 'organizations'" in js
    assert "name === 'organisation'" in js
    assert "function openOrganizationDetail(" in js and "function renderUnmatched(" in js
    assert "'/api/v1/organizations/candidates" in js and "'/api/v1/organizations/unmatched'" in js
    assert "drawerError('Impossible de charger l" in js   # fiche organisation en erreur
    assert "Pourquoi cette proposition" in js
    assert js.count('class="text-muted list-empty"') == 3

def test_organizations_visible_values_are_labelled():
    js = ...
    from geneweb_py.core.organization import OrganizationType
    for t in OrganizationType: assert f"{t.value}:" in js, t
    for source in ("tag", "place", "typed_event", "occupation_text"): assert f"{source}:" in js
    assert "formatGwName(org.name)" in js or "formatGwName(o.name)" in js

def test_export_tab_offers_organization_files():
    html, js = ...
    for i in ("btn-export-org-json", "btn-export-org-csv", "btn-export-org-links-csv"): assert f'id="{i}"' in html, i
    assert "#valider-et-enrichir" in html
    assert "'organization-links-csv': 'liens_organisations.csv'" in js
    assert "EXPORT_EXT" not in js

def test_stats_show_candidate_count_linking_to_tab():
    js = ...
    assert "'/api/v1/organizations/candidates?size=1'" in js
    assert "Organisations candidates" in js and "#/organisations" in js
```

Mettre à jour `test_detail_opens_in_side_drawer_not_inside_list` (`list-empty` passe de 2 à 3) et `test_views_are_driven_by_hash_routes` (ajouter `organisations`, `organisation`).

- [ ] **Step 2: Vérifier l'échec**

Run: `uv run python -m pytest tests/api/test_static_frontend.py -q`
Expected: les nouveaux tests et celui des onglets FAIL.

- [ ] **Step 3: index.html**

Onglet et panneau décrits dans l'interface ; texte d'intro : « Regroupements déduits des événements personnalisés, des professions et des événements typés. Ce sont des propositions : rien n'est modifié dans votre fichier. » ; sous la liste, `<details id="orgs-unmatched">` fermé, avec la phrase « C'est ici que l'on voit quelles règles manquent. » ; bloc Export avec le paragraphe (« Le fichier compagnon `.org.json` contient les organisations proposées et leurs liens avec les personnes ; votre `.gw` n'est pas modifié. Les deux CSV s'ouvrent dans un tableur pour valider ligne à ligne : voir « Valider et enrichir » dans le README. »).

- [ ] **Step 4: app.js : routes, liste, filtres**

`parseRoute` : `(id !== null) === (name === 'personne' || name === 'famille' || name === 'organisation')`. `applyRoute` : cas `organisations` → `applyOrganizationsRoute(route.params)` (lit `page`, `sort`, `type`, `source`, `q`, ferme le tiroir) ; cas `organisation` → onglet affiché puis `openOrganizationDetail(route.id)` sous le même `_routeSeq` que les personnes. `loadOrganizations()` construit `page`, `size=20`, `sort`, `type`, `named_from`, `q` et appelle `apiJson`. `renderOrganizations()` : une `div.item-row.org-card` par candidat (nom via `formatGwName`, libellé de type, lieu, « N personnes · M événements », période `first_year–last_year` ou année seule, pastilles `span.badge-pgw` : « collectif », « à revoir », « à déterminer » (si `to_determine`), « cercle », mot déclencheur, source quand `named_from !== 'tag'` d'après `NAMED_FROM_LABELS`), bouton `.btn-see` → `navigate(organizationHash(id))` (re-clic : retour à la liste comme pour les personnes). Vide : « Aucune organisation candidate. » et `orgs-unmatched` ouvert (`open = true`). Recherche à la frappe avec `wireInstantSearch` existant si sa signature le permet, sinon `Entrée`/bouton.

- [ ] **Step 5: app.js : fiche, reste à classer, exports, Stats**

`openOrganizationDetail(id)` : `setDrawerLoading`, `apiJson('/api/v1/organizations/candidates/' + encodeURIComponent(id))`, erreur → `showInDrawer(drawerError('Impossible de charger l\'organisation.'), 'organization', id, …)`. `buildOrganizationPanel(org)` : en-tête (type, lieu, effectifs, période, pastilles), liste des membres `<ul class="org-members">` (nom `<a href="${escHtml(personHash(m.person_id))}">`, rôle, date, lieu, « N témoins » si > 0), lieux distincts, `<details class="drawer-details"><summary>Pourquoi cette proposition ?</summary>` (source du nom, mot déclencheur, confiance en %, sources). Fil d'Ariane : `{ hash: organizationHash(id), label: formatGwName(org.name), title: 'Organisation ' + formatGwName(org.name) }`. `loadUnmatched()` au premier affichage de l'onglet : `summary` = « Reste à classer (N événements) », groupes en `<details>` imbriqués (« mot · effectif »), événements : personne cliquable, tag lisible, date, lieu. Export : `wireExportTab` ajoute les trois boutons ; `downloadExport(format)` utilise `EXPORT_FILENAMES[format]`. `renderStats` : carte `stat-card` « Organisations candidates » avec `pagination.total` de `/api/v1/organizations/candidates?size=1`, enveloppée dans `<a href="#/organisations">`.

- [ ] **Step 6: style.css**

`.orgs-bar` (flex, wrap, gap 0.5rem), `.org-card .org-meta`, `.badge-pgw` (pastille neutre) et variantes `.badge-review`, `.badge-collective`, `.badge-circle`, `.org-members li`, `.unmatched-group summary`. Mobile : la barre passe en colonne sous 767.98px.

- [ ] **Step 7: Vérifier les tests puis l'app réelle**

Run: `uv run python -m pytest tests/api -q` → PASS. Puis `uv run python run_api.py` et, dans le navigateur sur `http://127.0.0.1:8000`, charger `tests/fixtures/rich_pevt_wit.gw` : onglet visible, liste (vide ou non) sans erreur console, reste à classer déplié, fiche ouverte par `#/organisation/<id>` d'un candidat obtenu sur une fixture à deux personnes (créer au besoin un `.gw` synthétique dans le scratchpad), les trois téléchargements. Vérifier aussi sur la base réelle locale (sans capture d'écran versionnée).

- [ ] **Step 8: Commit**

```bash
git add src/geneweb_py/api/static/index.html src/geneweb_py/api/static/app.js src/geneweb_py/api/static/style.css tests/api/test_static_frontend.py
git diff --cached --name-only
git commit -m "feat(webapp): organizations tab with candidates, unmatched events and exports"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (l.111 formats ; snippet l.189 ; nouvelle section « Valider et enrichir » après « 6. Lancer l'application d'enrichissement » l.214-228 et avant « Analyse de réseaux » l.230)
- Modify: `README.en.md` (mêmes emplacements, titre « Validate and enrich »)
- Modify: `core/AGENTS.md` (carte `api/`, backlog)

- [ ] **Step 1: README fr et en**

Ligne formats : « export GEDCOM, JSON, XML ; fichier compagnon `.org.json` et CSV des organisations candidates, produits par la bibliothèque (`formats.org_sidecar`) et par l'onglet Export de la webapp (l'export JSON ne le contient pas) ». Le snippet Python de la section 4 (`#Cours_peinture 1890 #p [Atelier_Rose]_-_Lyon`) garde sa sortie « Atelier Rose » (le complément à mot d'établissement l'emporte) : le vérifier en l'exécutant. Dans le tableau « 1. Règles » (l.70), mentionner l'ordre complément à mot d'établissement > tag > « à déterminer ». Section « Valider et enrichir » (ancre `#valider-et-enrichir`, utilisée par l'onglet Export) : trois paragraphes courts + le tableau de § 7 du spec (voie 1 Streamlit, voie 2 outils), adapté et non recopié ; la version anglaise traduit, ancre `#validate-and-enrich` (mettre à jour le lien de l'onglet Export vers l'ancre française, le README anglais y renvoyant aussi).

- [ ] **Step 2: `core/AGENTS.md`**

Carte : `routers/{persons,families,events,genealogy,sessions,organizations}.py`, `services/organization_candidates.py`, `services/organization_exports.py`, `models/organization.py`, et une ligne sous `event_to_organization.py` (« règles Autre, `TYPED_EVENT_RULES`, texte de profession »). Retirer la ligne de backlog « Export CSV individus / organisations / événements » ou la réduire à « individus / événements ».

- [ ] **Step 3: Vérifier et commit**

Run: `rtk proxy grep -n "valider-et-enrichir" README.md core/src/geneweb_py/api/static/index.html` → les deux fichiers répondent.

```bash
git add README.md README.en.md core/AGENTS.md
git diff --cached --name-only
git commit -m "docs: organization candidates exports and validation workflow"
```

---

### Task 7: Vérification finale

- [ ] **Step 1: Suite complète, couverture, lint**

Run (depuis `core/`) : `COLUMNS=250 uv run python -m pytest -q --cov=geneweb_py --cov-report=term-missing:skip-covered | tail -5 && uv run mypy src/geneweb_py/ && uv run ruff check src tests --ignore E501 && uv run ruff format --check src tests`
Expected: 0 échec, couverture totale ≥ 80 %, mypy 0 erreur, ruff propre. Depuis la racine : `uv lock --check` inchangé (aucune dépendance ajoutée).

- [ ] **Step 2: Relecture des données**

Run: `git log --stat origin/main..HEAD` puis `git diff origin/main..HEAD --stat` : aucun `.gw`/`.csv`/`.org.json` hors `tests/fixtures`, aucun nom réel dans les diffs (`git diff origin/main..HEAD | rtk proxy grep -c "DUPONT"` sert de contrôle que seuls des noms synthétiques apparaissent).

- [ ] **Step 3: Ne pas pousser**

S'arrêter ici et demander à l'utilisateur s'il souhaite `git push` (et un redéploiement Coolify).

---

## Auto-relecture (faite à la rédaction)

- Couverture du spec : § 3.1 (seuil, reste à classer) → T3 ; § 3.2-3.4 → T1 ; § 3.5 (collectif) → T3 ; § 3.6-3.8 → T1 ; § 4 routes → T3, exports → T4 (+ T2) ; § 5.1-5.3 → T5 ; § 5.4 contraintes → T5 tests ; § 6 → T6.
- Point ouvert tranché ici : la référence lien ↔ événement est `pevt:<person_id>:<index>` posée par le moteur (sérialisable dans le `.org.json`, indépendante de `id(event)`), distincte de `stable_event_id` de l'API qui reste pour l'onglet Événements.
- Priorité validée par l'utilisateur (§ 3.2) : complément à mot d'établissement > tag qui dit plus qu'un rôle > « à déterminer » avec l'extraction la plus probable. L'exemple historique `#Cours_peinture … [Atelier_Rose]` garde « Atelier Rose ».
- Mode d'exécution choisi : subagent-driven.
