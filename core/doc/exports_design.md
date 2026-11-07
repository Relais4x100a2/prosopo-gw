# Exports de la webapp : conception globale

Statut : conception validée (2026-11-06). Remplace l'ancienne conception des pistes, devenue le § 6.

## 1. Intention

La webapp sert à un **premier tri rapide** des organisations. L'affinement se fait en aval, dans
les outils des humanités numériques (tableur, OpenRefine, Dataiku, ETL). L'export est le passage de relais : il
doit contenir tout ce dont l'aval a besoin, sous une forme lisible par trois lecteurs :

- **un humain**, dans un tableur ;
- **des outils de données** (pandas, SQL, ETL) ;
- **un LLM**, si l'utilisateur en choisit un hors du dépôt (aucun n'est fourni).

Aujourd'hui, sept boutons coexistent (GEDCOM, JSON, XML, compagnon `.org.json`, trois CSV
d'organisations). Les exports de la base ne contiennent aucune organisation. Le reste à classer et
les pistes tirées des notes ne sont exportés nulle part. Le compagnon n'est pas rechargeable.

## 2. Objectifs, non-objectifs, anti-objectifs

Objectifs :

- **Un seul bouton** dans la webapp : « Télécharger les données (.zip) ».
- Un **jeu unique de tables** reliées par des identifiants stables, décliné en CSV, JSON et SQLite.
- Le reste à classer, les **pistes** tirées des notes et les **sources** sont exportés.

Non-objectifs (décisions de l'utilisateur) :

- **Pas de rechargement** du compagnon dans la webapp : l'aval affine, la webapp ne reprend pas.
- **Pas de XML-TEI** dans ce chantier (§ 9).
- Pas de décomposition des sources multiples ni d'extraction des sources écrites dans les notes (§ 9).
- Aucun appel LLM dans `core`.

Anti-objectifs (échec même si « ça marche ») :

- Deux formats qui divergent : une colonne présente en CSV et absente en SQLite.
- Une table qu'on ne peut pas relier aux autres faute d'identifiant commun.
- Des listes cachées dans une cellule (« rôle1, rôle2 ») là où une table de liens s'impose.
- Un fichier exporté versionné : le zip contient des données personnelles, il reste local.

## 3. Deux branches

| Branche | Contenu | Fichier |
|---|---|---|
| **Mon travail** | Décisions de la session : organisations et liens, mots ignorés | `base.org.json` (compagnon) |
| **Les données** | Tout ce qui est lu ou calculé, en tables | `base.sqlite`, `base.json`, `csv/*.csv` |

Le `.gw` reste la source de vérité et n'est jamais modifié. Le compagnon garde son format actuel
(`formats/org_sidecar.py`), plus une clé `ignored_words` ; l'import existant ignore les clés
inconnues, donc un ancien lecteur continue de fonctionner.

## 4. Les tables

Conventions communes :

- Une ligne par chose ; aucune liste dans une cellule.
- Les identifiants sont les mêmes dans toutes les tables (§ 4.2).
- Code et libellé côte à côte quand un code existe : `type` (`deat`) et `type_libelle` (« Décès »).
- Dates en double : `date` (texte GeneWeb tel quel, « ~1850 », « 1850..1855 ») et `annee` (entier
  pour trier : `Date.sort_year()`, vide si inconnue).
- Noms de colonnes en français, sans accents, en `snake_case`, comme les CSV actuels.

### 4.1 Liste

| Table | Une ligne par | Colonnes |
|---|---|---|
| `personnes` | personne | `personne_id`, `nom`, `prenom`, `occurrence`, `sexe`, `naissance_date`, `naissance_annee`, `naissance_lieu`, `deces_date`, `deces_annee`, `deces_lieu`, `profession`, `note` |
| `familles` | famille | `famille_id`, `mari_id`, `femme_id`, `mariage_date`, `mariage_annee`, `mariage_lieu`, `note` |
| `enfants` | enfant d'une famille | `famille_id`, `personne_id`, `rang` |
| `evenements` | événement personnel ou familial | `evenement_id`, `personne_id` (vide pour un familial), `famille_id` (vide pour un personnel), `type`, `type_libelle`, `libelle`, `date`, `annee`, `lieu`, `ville`, `complement`, `note` |
| `temoins` | témoin d'un événement ou d'une famille | `evenement_id` ou `famille_id`, `personne_id`, `role` (libellé : témoin, parrain ou marraine…) |
| `sources` | texte de source tel qu'il est dans la base | `source_id`, `cible` (`personne`, `evenement`, `famille`), `cible_id`, `objet` (`generale`, `naissance`, `bapteme`, `deces`, `sepulture`, `mariage`, `enfants`, `evenement`), `texte` |
| `organisations` | organisation candidate | colonnes de l'actuel CSV des organisations, `organisation_id` en tête |
| `liens` | lien personne-organisation | colonnes de l'actuel CSV des liens, plus `evenement_id` et `temoin` |
| `reste_a_classer` | événement non classé | `evenement_id`, `mot` |
| `pistes` | extrait de note | § 6.3 |
| `experiences_proches` | expérience proche | colonnes de l'actuel CSV |

`note` contient le texte complet, les notes multiples séparées par un saut de ligne :
`Person.notes` pour `personnes`, `Family.comments` pour `familles`, `Event.notes` pour
`evenements`. En prosopographie, ces notes portent des synthèses biographiques que l'ETL et le
LLM doivent lire sans rouvrir le `.gw` (utilisateur).

### 4.2 Identifiants

| Entité | Identifiant | Exemple synthétique |
|---|---|---|
| personne | `Person.unique_id` | `DUPONT_Jean_0` |
| famille | `Family.family_id` | `FAM_012` |
| événement personnel | `event_ref(person_id, index)` (existant) | `pevt:DUPONT_Jean_0:2` |
| événement familial | `fevt:<famille_id>:<index>` (nouveau, symétrique) | `fevt:FAM_012:0` |
| organisation | `Organization.id` (existant) | `usine_martin_roubaix` |
| source, piste | hachage court et stable de la cible et de la position | `s-3f9a1c2b7d10` |

Les identifiants dépendent de l'ordre du `.gw` : stables pour un même fichier, pas d'une version
de la base à l'autre. C'est suffisant sans rechargement (§ 2).

### 4.3 Sources

Chaque champ de source non vide du modèle devient une ligne, texte inchangé :
`Person.person_source`, `birth_source`, `baptism_source`, `death_source`, `burial_source`,
`Family.family_source`, `marriage_source`, `common_children_source`, `Event.source`. Une même
source n'est pas répétée quand le parseur l'a recopiée à la fois sur la personne et sur l'événement
de naissance (dédoublonnage par cible, objet et texte).

Évolution prévue sans casser la table : la décomposition d'un texte multiple ajoutera des lignes
filles et une colonne `source_parent`.

## 5. Formats et archive

### 5.1 Contenu du zip

```
prosopo-<base>-<AAAA-MM-JJ>.zip
  LISEZMOI.txt         contenu, usage de chaque fichier, rappel : données personnelles
  dictionnaire.csv     table ; colonne ; type ; description
  base.org.json        mon travail (compagnon)
  base.sqlite          toutes les tables
  base.json            toutes les tables
  csv/
    personnes.csv  familles.csv  enfants.csv  evenements.csv  temoins.csv  sources.csv
    organisations.csv  liens.csv  reste_a_classer.csv  pistes.csv  experiences_proches.csv
```

`<base>` est le nom du fichier `.gw` chargé, sans extension.

### 5.2 Une seule définition, trois rendus

Une définition unique des tables (nom, colonnes, type de chaque colonne : texte, entier, décimal,
booléen) produit les trois formats. `dictionnaire.csv` est généré depuis cette même définition.
Un test vérifie que les trois rendus ont les mêmes tables, colonnes et nombres de lignes.

| Format | Réglé pour | Valeurs |
|---|---|---|
| CSV | tableur français | UTF-8 avec BOM, séparateur `;`, booléens `oui`/`non`, décimaux à virgule, protection contre les formules (conventions de `organization_exports.py`) |
| JSON | Streamlit, LLM, scripts | `{"format": "prosopo-gw/export", "version": 1, "generated_at": "…", "base": "…", "tables": {"personnes": [{…}], …}}` ; valeurs typées (`true`, `1850`, `0.8`), `null` pour vide |
| SQLite | SQL, pandas, DB Browser | une table par table, types `TEXT` / `INTEGER` / `REAL`, booléens 0/1, clé primaire sur l'identifiant, index sur les colonnes `*_id` ; module `sqlite3` de la bibliothèque standard, aucune dépendance ajoutée |

### 5.3 Où vit le code

- `src/geneweb_py/formats/tables.py` : définition des tables et construction des lignes depuis une
  `Genealogy` (bibliothèque, sans dépendance API), donc utilisable par un ETL ou par Streamlit.
- `src/geneweb_py/formats/table_writers.py` : rendus CSV, JSON, SQLite et zip.
- Les tables qui dépendent de l'index des candidates (`organisations`, `liens`, `reste_a_classer`,
  `experiences_proches`) reçoivent l'index en paramètre.
- Route `GET /api/v1/genealogy/export/zip` ; les routes d'export actuelles restent, sans bouton.

## 6. Pistes tirées des notes

### 6.1 Sources lues

Notes de la personne, de ses événements, de ses familles et des événements familiaux. Les notes de
base (`notes-db`, pages, wizard) ne sont pas lues : elles ne sont rattachées à personne. Une note
de famille est rattachée au mari, sinon à la femme. Une note d'événement Profession n'est pas
reprise si elle a nommé l'organisation liée à cet événement.

### 6.2 Détection et extrait

Adresses web retirées avant la recherche. Déclencheur : un mot de `ESTABLISHMENT_WORDS` ou une
forme de `LEGAL_FORMS`, comparé sans casse ni accents. Écartés : « en compagnie de », les mots
ignorés de la session. « Compagnie » suivie d'un nombre reste une piste, type deviné `military`.

Piste **forte** : mot de `COMPANY_NAME_TRIGGERS` à majuscule suivi (après au plus un mot de
liaison) d'un mot à majuscule, ou mot à majuscule suivi d'une forme juridique.

Extrait : 150 caractères de chaque côté, élargis aux limites de mots ; fenêtres qui se recouvrent
fusionnées ; espaces réduites ; 600 caractères au plus.

### 6.3 Colonnes de la table `pistes`

`piste_id`, `personne_id`, `evenement_id` (vide pour une note de personne ou de famille),
`famille_id` (vide hors famille), `nature` (`organisation` ; `source` réservé au § 9),
`origine` (`personne`, `evenement`, `famille`, `evenement_familial`), `mots` (déclencheurs repliés,
séparés par une espace : exception assumée à la règle « pas de liste », un mot n'étant pas une
entité), `type_devine`, `forte`, `extrait`.

Le contexte (date, lieu, type de l'événement, conjoint) n'est pas recopié : il se lit dans
`evenements` et `familles` par l'identifiant. L'aval fait la jointure.

## 7. Webapp

- Le panneau d'export ne garde qu'un bouton : « Télécharger les données (.zip) », avec une ligne
  qui résume le contenu (nombres de personnes, organisations, événements à classer, pistes).
- Les boutons GEDCOM, JSON, XML, compagnon et les trois CSV disparaissent ; leurs routes restent.
- Pas de section « Pistes étendues » dans l'onglet Organisations.

## 8. Streamlit (consommateur, plan séparé)

> **Mise à jour (novembre 2026)** : l'enrichissement par LLM est abandonné
> (`organizations_candidates_design.md` § 8). Le rôle de l'application est à redéfinir ; le
> paragraphe ci-dessous décrit l'intention initiale.

Usage local. Charge `base.json` (ou `base.sqlite`), joint `reste_a_classer` et `pistes` à leur
contexte, envoie au LLM par lots, fait valider. Les propositions validées restent dans Streamlit ;
leur consolidation dans un export sera décidée plus tard. Le changement de source de l'app (du
`.gw` vers `base.json`) fait partie de ce plan séparé.

## 9. Hors chantier, consigné pour plus tard

- **GEDCOM** : convertisseur conservé, sans bouton, comme contrôle complémentaire de fidélité face
  au GEDCOM de GeneWeb ou Geneanet. L'étalon principal reste l'aller-retour `gwc`/`gwu`
  (`parser_fidelity_audit.md`).
- **XML maison** : sans bouton ; code conservé.
- **XML-TEI** : export futur pour les chercheurs (XPath, XQuery) : `listPerson`, `listOrg`,
  `listRelation`.
- **Sources** : décomposition des textes multiples (`source_parent`) ; repérage des sources écrites
  dans les notes, comme pistes de `nature = source` (« AD », « registre », « acte », « cote »…).
- **Rechargement du compagnon** dans la webapp, avec import tolérant si la base a changé.

## 10. Tests

Fixtures synthétiques uniquement. À couvrir :

- chaque table sur une petite base (personnes, familles, enfants, événements personnels et
  familiaux, témoins de famille et d'événement) ;
- sources : chaque champ, dédoublonnage naissance ;
- identifiants : stables d'un appel à l'autre, et toute référence `*_id` résolue dans sa table ;
- parité des trois rendus (tables, colonnes, nombres de lignes) et `dictionnaire.csv` complet ;
- CSV : BOM, `;`, `oui`/`non`, formule neutralisée ;
- SQLite : ouverture et jointure `liens` × `personnes` ;
- zip : liste exacte des fichiers, nom de l'archive ;
- pistes : chaque origine, URL retirée, « en compagnie de », « Compagnie 3 », fusion, borne de
  600, forte et faible, note de Profession exploitée non reprise, mot ignoré, note vide ou réduite
  à une URL, mot en capitales accentuées ;
- route zip et nouveau panneau d'export.

## 11. Décisions

Utilisateur :

- Deux branches : mon travail (compagnon) et les données (tables).
- Un seul bouton zip ; le compagnon est dans le zip, sans bouton à part.
- Pas de rechargement dans la webapp ; affinement en aval (ETL, Streamlit).
- Table `sources` dédiée ; CSV + JSON + SQLite dans un zip.
- GEDCOM et XML retirés de l'interface, code conservé ; TEI plus tard.
- Notes complètes exportées dans `personnes`, `familles` et `evenements` (colonne `note`).
- Contexte des pistes par jointure ; identifiants stables par fichier ; zip découpé par format.

Choix de conception :

- Familles, enfants et témoins ajoutés aux tables.
- `mots` des pistes séparés par une espace dans une cellule.
- Pistes : extraits de 150 caractères, fusionnés, bornés à 600.
