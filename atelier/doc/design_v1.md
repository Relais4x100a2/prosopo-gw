# Prosopo-gw-Atelier : conception de la v1 (pivot et lieux)

Statut : **conception validée par l'auteur**, 7 novembre 2026. Nom provisoire « Prosopo-gw-Atelier ». Le nom
définitif sera choisi plus tard.
Évolution : depuis le 8 novembre 2026, un lieu est une chaîne de niveaux (communes historiques
comprises) ; le modèle est décrit dans
`docs/superpowers/specs/2026-11-08-atelier-lieux-niveaux-design.md`. Ce document reste la
référence pour le reste ; ses passages sur les champs fixes (`ancien_nom`, `lieux`) sont remplacés.
Origine : `docs/reflexions/2026-11-06-atelier-nettoyage.md`, § 9, où sont consignées les décisions
de l'auteur. Ce document en tire une conception que l'on peut planifier. Les choix marqués
**(choix de conception)** sont des propositions de l'assistant, pas des décisions de l'auteur.

## 1. Intention

Les historiens et les ingénieurs en humanités numériques qui travaillent sur une base GeneWeb
doivent la nettoyer avant de l'exploiter. Ils le font aujourd'hui à la main, dans un tableur ou
OpenRefine. Le travail est long et il est à refaire à chaque nouvelle version de la base.

L'atelier est une **application locale** qui les fait entrer dans un processus guidé de nettoyage
et d'enrichissement du résultat du parser `geneweb-py`. Il en sort un **jeu de données propre et
traçable**, prêt à importer dans leur propre base. La v1 traite **les lieux** : remettre de la
cohérence dans des écritures disparates, pour pouvoir **géocoder facilement ensuite**.

Ce qui rend l'outil précieux : **une décision prise une fois n'est jamais à refaire**, quel que
soit le `.gw` rechargé (le même, une version modifiée, ou une autre base).

## 2. Public

- **Visé** : historiens, ingénieurs en humanités numériques. Ils savent lancer une commande
  `uv tool install`. Ils importent ensuite les données dans SQL, Heurist, nodegoat, Omeka S,
  FactGrid, un graphe RDF ou de la XML-TEI.
- **Hors cible** : le généalogiste amateur. Il garde la webapp publique de `core` (vitrine sur
  Coolify, sans LLM).

## 3. Objectifs, non-objectifs, anti-objectifs

**Objectifs de la v1**

1. Charger un `.gw` et en extraire toutes les écritures de lieu.
2. Décomposer chaque écriture en éléments typés, en s'appuyant sur le **COG INSEE** embarqué
   et la base des codes postaux (décision de l'auteur, § 6.1).
3. Proposer des regroupements (clusters) d'écritures qui désignent la même commune.
4. Les faire valider par cluster, dans l'écran « liste + détail » (§ 7).
5. Retenir chaque décision dans un **référentiel personnel de lieux**, réappliqué d'office à tout
   `.gw` chargé ensuite.
6. Exporter un **pivot** : les tables de `core` plus une table `lieux` reliée par identifiant.

**Non-objectifs (v1)**

- Réécrire un `.gw`. C'est abandonné : la sortie est un jeu de données importable.
- Les sources et les organisations : ce seront les étapes suivantes de l'atelier.
- Le géocodage lui-même. La v1 le prépare ; les enrichissements du § 8 viennent par lots ensuite.
- Le LLM. Le point d'accroche est prévu (§ 10), sans implémentation.
- Les exceptions de contexte (§ 11.1).
- Le travail à plusieurs en même temps sur un même référentiel.

**Anti-objectifs (échec même si « ça marche »)**

- **Appliquer quelque chose sans validation humaine.** Une proposition, d'une règle ou plus tard
  d'un LLM, reste une proposition tant qu'elle n'est pas validée. Seules les décisions déjà
  prises s'appliquent d'office (§ 6.3).
- **Perdre le texte d'origine.** Chaque occurrence garde son écriture brute à côté du lieu retenu.
- **Faire refaire une décision déjà prise.**
- **Envoyer des données hors de la machine sans action explicite.** Le serveur n'écoute que sur
  `127.0.0.1`.
- **Dupliquer `core`.** L'atelier appelle la bibliothèque, il n'en recopie pas la logique.

## 4. Contraintes

- **Dépôt public** (`AGENTS.md` § 2) : aucune donnée réelle. Pas de `.gw` réel, pas de nom de
  personne réelle, pas de référentiel personnel réel dans Git. Les tests utilisent des fixtures
  synthétiques. Les noms de communes réelles sont permis dans les tests de décomposition et de
  regroupement : ce ne sont pas des données de personnes.
- **Workspace `uv` uniquement**, Python ≥ 3.11 pour l'atelier. `core` n'est pas modifié pour
  l'atelier.
- **Séparation nette** (décision de l'auteur) : `core` garde l'essentiel (parser, modèle,
  fonction organisations, tables et zip, webapp vitrine). Tout le traitement et l'enrichissement va
  dans l'atelier. Pas de scripts d'atelier dans la CLI de `core` : une seule porte d'entrée par
  fonction.
- L'atelier dépend de l'API publique de `core`, à garder stable : `GeneWebParser`,
  `formats.tables.build_base_tables` et `TableSpec`, `formats.table_writers`,
  `core.place.parse_place`.

## 5. Architecture

### 5.1 Place dans le monorepo

- Un nouveau membre du workspace, **`atelier/`** (le nom de dossier suivra le nom définitif),
  paquet `prosopo-gw-atelier`, commande `prosopo-gw-atelier`. **(choix de conception)**
- **Diffusion (décision de l'auteur)** : `geneweb-py` est publié sur PyPI **d'abord**, puis
  l'atelier, qui s'installe par `uv tool install prosopo-gw-atelier`. L'atelier déclare une
  dépendance versionnée sur `geneweb-py` ; dans le workspace, elle se résout localement comme
  aujourd'hui. Prérequis : aligner `core` sur `requires-python = ">=3.11"` (décision de
  l'auteur : Python 3.8 n'est plus maintenu, et tout le monorepo est ainsi homogène pour la
  publication), et ajouter à la CI une étape de publication, déclenchée par une étiquette de
  version.
- `app/` (Streamlit, pages LLM) est **retiré** ; son historique reste dans Git (§ 12).

### 5.2 Pile

- **Serveur** : FastAPI + uvicorn, comme la webapp de `core`. La commande démarre le serveur sur
  `127.0.0.1`, sur un port libre, puis ouvre le navigateur.
- **Interface** : HTML et JavaScript sans framework, avec Bootstrap et Tabulator, comme la webapp
  de `core`. Ces fichiers sont recopiés dans l'atelier, pas importés depuis `core` : l'interface
  de l'atelier ne doit pas dépendre de l'emplacement des fichiers statiques de `core`.
  **(choix de conception)**
- **Stockage** : SQLite (module `sqlite3` de la bibliothèque standard), aucune dépendance
  ajoutée. **(choix de conception)**

### 5.3 Flux

```
.gw ──GeneWebParser──▶ Genealogy ──build_base_tables──▶ tables de core
                                                        │
                    écritures de lieu ◀─────────────────┘
                          │
            décomposition (§ 6.1) ─▶ référentiel personnel : déjà décidé ?
                          │                       │ oui : rattachement d'office
                          │ non                   ▼
                    regroupement (§ 6.2) ─▶ file de validation (§ 7) ─▶ décisions
                                                                          │
                     export pivot (§ 9) ◀── référentiel personnel ◀───────┘
```

## 6. L'étape des lieux

### 6.1 Collecte et décomposition

**Collecte.** Toutes les colonnes de lieu des tables de `core` : `personnes.naissance_lieu`,
`personnes.deces_lieu`, `familles.mariage_lieu`, `evenements.lieu`. Une **écriture** est une chaîne
distincte, telle que le parser la rend (les `_` GeneWeb déjà décodés). Elle est comptée avec ses
occurrences (personne ou famille, type d'événement, date).

**Complément.** `parse_place` de `core` sépare `[Complément]_-_Ville`. Le complément (adresse,
établissement) **n'est pas une variante de la commune** : on le garde à part. L'écriture est
regroupée sur sa partie commune, et le complément est conservé dans le pivot (`complement`). C'est
le pont vers la fonction organisations de `core`.

**Décomposition.** Chaque écriture est découpée en éléments typés :

| Élément | Exemples d'indices |
|---|---|
| `commune` | segment principal ; abréviations `St`/`Ste` développées pour la comparaison |
| `code_postal` | 5 chiffres reconnus comme code postal |
| `code_insee` | 5 caractères (chiffres, `2A`/`2B` pour la Corse) reconnus comme code INSEE |
| `departement` | nom, numéro, `(59)` |
| `region` | régions actuelles **et anciennes** (une ancienne région reste une région) |
| `pays` | liste de pays |
| `commune_historique` | ancienne commune (fusion, association, délégation) reconnue par le COG ; un simple changement de nom reste un ancien nom de la commune |

Les séparateurs (virgule, parenthèses, tiret entre commune et code), la casse et l'ordre varient :
la décomposition ne suppose aucun ordre fixe. Un nombre à 5 chiffres peut être un code postal ou un
code INSEE. Sans référentiel pour trancher, il est marqué **ambigu**, sans être deviné.

**COG INSEE dès la v1 (décision de l'auteur).** Le Code officiel géographique (communes, codes,
départements, régions, et son historique des communes : fusions, changements de nom) est lu hors
ligne, avec la base des codes postaux ci-dessous. Il sert à :
- vérifier qu'un code à 5 caractères est un code INSEE existant, et lever ainsi une partie de
  l'ambiguïté code postal / code INSEE ;
- reconnaître une commune et son département, y compris sous un ancien nom ou une commune
  fusionnée (alimente `commune_historique`) ;
- donner au regroupement une clé forte (le code INSEE) même quand l'écriture n'en contient pas.

Le COG ne contient pas les **codes postaux**. **Base officielle des codes postaux embarquée
(décision de l'auteur)** : celle de La Poste, publiée sur data.gouv.fr sous Licence Ouverte 2.0,
comme le COG. Elle fait la correspondance code postal ↔ code INSEE ↔ commune. Avec les deux
bases, un nombre à 5 chiffres est tranché nativement : code INSEE, code postal, ou les deux
possibles (on retient alors celui qui s'accorde avec la commune écrite à côté). Un code postal
couvre souvent plusieurs communes : seul, il propose ces communes sans en choisir une ; avec un
nom de commune, il la confirme.

**Embarqué, millésime figé** **(choix de conception)** : un millésime du COG et de la base des codes postaux est livré dans le
paquet, compressé, pour fonctionner sans réseau et rendre les résultats reproductibles. Le
millésime utilisé est inscrit au journal et dans le `LISEZMOI` de l'export, avec la mention de
la source exigée par la Licence ouverte Etalab. La mise à jour d'un millésime est une nouvelle
version du paquet.

Les autres listes (régions anciennes, pays) sont **petites, statiques et embarquées**. Les régions
d'avant 2016 viennent du COG ; les découpages plus anciens (provinces, départements disparus)
relèvent de l'historicité (§ 8). **(choix de conception)**

Chaque élément décomposé porte l'**indice** qui l'a reconnu (nom, code postal, code INSEE,
ancienne région…). L'écran de validation l'affiche.

### 6.2 Regroupement

- **Clé de comparaison** : commune normalisée (sans casse ni accents, tirets et espaces unifiés,
  `St` devenu `Saint`) + département quand il est connu.
- **Code INSEE** : une clé forte. Deux écritures qui portent le même code vont ensemble.
- **Similarité** de chaînes pour les cas proches (fautes, abréviations). Elle ne produit que des
  propositions de confiance moyenne ou faible.
- **Confiance** du cluster : haute, moyenne ou faible. Elle sert à trier la file : les clusters
  sûrs d'abord.
- Une commune sans département connu, présente dans plusieurs départements, ne doit **pas** être
  fusionnée d'office : le cluster est marqué faible.

Les seuils et les algorithmes de similarité sont laissés au constructeur (§ 13), qui les calera
sur des fixtures représentatives.

### 6.3 Décisions et référentiel personnel

**Principe (décision de l'auteur).** Une décision porte sur **la valeur**, pas sur une position
dans un fichier : « l'écriture `ROUBAIX, Nord, France` désigne le lieu Roubaix (59512) ». Elle
se réapplique à tout `.gw` chargé ensuite.

- **Clé d'une décision** : le texte exact de la **partie lieu** de l'écriture, telle que le parser
  la rend, **complément retiré** (`parse_place(...).name`). Ainsi la décision prise sur `Lyon` vaut
  aussi pour `[Atelier Rose]_-_Lyon` et pour tout nouveau complément, sans rien refaire. Le
  complément est un attribut de l'**occurrence**, pas de la clé. Deux casses différentes restent
  deux écritures, donc deux entrées dans la table d'association ; mais valider un cluster les
  associe toutes **en un seul geste** au même `lieu_id`, sans rien saisir deux fois. La
  normalisation ne sert qu'à **proposer**. **(validé par l'auteur)**
- **Référentiel personnel** : il vit **hors des projets**, dans le dossier de données de
  l'utilisateur (par exemple `~/.local/share/prosopo-gw-atelier/`, selon le système). On peut le
  déplacer avec une option ou une variable d'environnement. **(choix de conception)**
  - `lieux` : lieu retenu, avec un identifiant **stable** (UUID), sa chaîne de niveaux (du plus
    précis au plus large), chaque niveau avec son origine (`ecrit`, `regle`, `manuel`, `insee`,
    plus tard `paris`, `dicotopo`, `geonames`, `llm`) et son statut (`valide` ou `propose`), et
    son code postal.
  - `ecritures` : écriture → `lieu_id`, ou statut `rejete` (pas un lieu exploitable : « en mer »).
  - `journal` : chaque action (valider, sortir des écritures, rejeter, corriger un niveau,
    accepter ou refuser une proposition, annuler), horodatée et ajoutée sans jamais rien effacer. C'est la trace détaillée.
- **Au rechargement d'un `.gw`** :
  - les écritures connues sont rattachées d'office et apparaissent « déjà décidé » ;
  - seules les écritures nouvelles entrent dans la file. Si elles ressemblent à un lieu déjà
    validé, elles sont proposées dans ce cluster ;
  - une écriture connue absente du nouveau fichier est simplement ignorée et reste dans le
    référentiel.
- **Corriger un lieu déjà validé** (changer sa forme retenue, en retirer une écriture) reste
  possible et s'inscrit au journal.
- **Partage** : le référentiel s'exporte et s'importe en fichier (JSON lisible, pour qu'on puisse
  le versionner et le comparer). À l'import, une écriture déjà décidée différemment est un
  **conflit**, à trancher à l'écran ; il n'est jamais écrasé en silence. **(choix de conception)**

### 6.4 Projet

Un **projet** relie un `.gw` (son chemin et une empreinte de son contenu) à l'état de son
traitement : la file, les clusters en cours, les filtres. Il est stocké sur disque, et l'on peut
le quitter puis le reprendre plusieurs jours après. L'empreinte permet de signaler que le `.gw` a
changé ; on recharge alors en gardant toutes les décisions (§ 6.3).

## 7. Écran de validation (validé par prototype, 7 novembre 2026)

Disposition **liste + détail**, retenue par l'auteur après un prototype cliquable.

**File (à gauche)**
- Les clusters, triés par confiance puis par nombre d'occurrences.
- Un état par cluster : à traiter, validé, rejeté, déjà décidé.
- Des filtres par état, et un compteur d'avancement en tête (« 412 clusters · 37 traités »).
- Un lieu né d'une scission apparaît **sous son lieu d'origine**, décalé (↳), avec un nom
  provisoire égal à sa première écriture.

**Cluster ouvert (à droite)**
- **La forme retenue** : sa chaîne de niveaux, du plus précis au plus large, chacun avec son nom,
  son type et son origine ; on peut corriger un niveau, en ajouter, en retirer, les réordonner,
  accepter ou refuser un niveau proposé. Le code postal est un attribut du lieu, à part.
- **Les compléments**, affichés à part : ils ne sont pas des variantes de la commune.
- **Les écritures d'origine** : une case à cocher, le nombre d'occurrences et l'indice de
  rattachement pour chacune.
- **Actions** :
  - **Valider** : enregistre la forme retenue et, **en un seul geste**, associe toutes les
    écritures cochées au même `lieu_id` dans le référentiel personnel (une entrée par écriture
    exacte, § 6.3). Si des écritures sont décochées, elles sont d'abord sorties dans un nouveau
    lieu.
  - **Sortir les décochées vers un nouveau lieu (n)** : le bouton reste grisé tant que rien n'est
    décoché, et le nombre suit les cases. Avant l'action, les écritures décochées sont barrées et
    estompées. Après l'action, **on reste sur le lieu d'origine** et un bandeau dit ce qui s'est
    passé (écritures sorties, nom du nouveau lieu, bouton « Ouvrir le nouveau lieu »). Le nouveau
    lieu clignote brièvement dans la file. Ce comportement vient des retours sur le prototype :
    la première version, « Scinder les décochées », ne montrait pas son résultat.
  - **Rejeter** : pas un lieu exploitable.
  - **Voir les occurrences** : les personnes et les événements concernés, pour lever un doute.
  - **Annuler** : la dernière action (Ctrl+Z).
- **Clavier** : V valider, S sortir, R rejeter, O occurrences, ↑/↓ naviguer.

Le prototype jetable reste visible en local dans
`.superpowers/brainstorm/…/content/prototype-lieux-v2.html` (non versionné) : il sert de référence
visuelle, pas de code à reprendre.

## 8. Enrichissements facultatifs (après la v1)

Décision de l'auteur : une fois les variantes regroupées, l'utilisateur choisit, et peut cumuler,
trois enrichissements. Ils s'appliquent aux **lieux retenus**, jamais aux écritures brutes.

1. **Lien à un référentiel** : un identifiant externe (code INSEE vérifié, QID Wikidata,
   GeoNames…).
2. **Coordonnées et hiérarchie** : latitude et longitude ; commune → département → région → pays.
3. **Historicité** : noms et rattachements anciens (paroisses, communes fusionnées, départements
   disparus).

**Référentiels visés** (décision de l'auteur : la France d'abord) : COG INSEE et son historique
des communes, base Cassini de l'EHESS, Wikidata, DicoTopo, SoDUCo, GeoHistoricalData, et des
projets du même type. SoDUCo et GeoHistoricalData portent surtout sur Paris et ses adresses : ils
serviront au niveau du complément (l'adresse), pas seulement à celui de la commune. **Les accès
(API, téléchargement), les licences et les conditions de réutilisation restent à vérifier, un
référentiel à la fois, avant chaque connecteur.**

**Forme commune** : un connecteur par référentiel, derrière une même interface : chercher des
candidats pour un lieu retenu, renvoyer identifiant, libellé, coordonnées et période de validité.
Les résultats sont des **propositions**, validées dans le même écran. Un cache local évite de
réinterroger le réseau. **(choix de conception)**

**Ordre proposé** : le COG est déjà dans la v1 (§ 6.1) ; viennent ensuite Wikidata (QID,
coordonnées, hiérarchie), puis les autres. **(choix de conception)**

## 9. Sortie : le pivot

Décision de l'auteur : un **schéma simple et unique**, adapté ensuite à chaque outil cible.

- **Base** : les tables de `core` (`build_base_tables`) telles quelles, avec les mêmes noms de
  colonnes et les mêmes conventions (`exports_design.md` § 4).
- **Ajouts** **(choix de conception)** :
  - une table `lieux` : `lieu_id`, `commune`, `code_insee`, `code_postal`, `departement`,
    `region`, `pays`, `commune_historique`, `code_insee_historique`, `libelle` (noms des niveaux),
    `latitude`, `longitude`. Pour chaque élément, une colonne `<élément>_origine` ;
  - une table `niveaux_lieux` : une ligne par niveau validé (`lieu_id`, `rang`, `nom`, `nom_ecrit`,
    `type`, `nature`, `identifiant`, `source`, `debut`, `fin`, coordonnées, `origine`) ;
  - une table `ecritures_lieux` : `ecriture` (partie lieu, sans complément), `lieu_id`,
    `statut` ;
  - à côté de chaque colonne de lieu des tables de `core`, une colonne `…_lieu_id`
    (`naissance_lieu_id`, `deces_lieu_id`, `mariage_lieu_id`, `lieu_id` dans `evenements`) et,
    là où `core` ne la fournit pas déjà, une colonne `…_complement` (`evenements.complement`
    existe). L'écriture d'origine reste dans sa colonne.
- **Formats en v1** : CSV, JSON, SQLite et le dictionnaire, produits par les fonctions de rendu
  de `core` (`table_to_csv`, `tables_to_json`, `tables_to_sqlite`, qui prennent des `Table`
  quelconques ; `dictionary_table` pour le dictionnaire).
- **Archive** : un zip propre à l'atelier, avec son propre `LISEZMOI.txt` (origine des valeurs,
  référentiel utilisé, rappel sur les données personnelles) et **sans** `base.org.json`.
  `build_zip` de `core` n'est pas réutilisé tel quel : il est propre au zip de la webapp.
  **(choix de conception)**
- **Adaptateurs ensuite**, dans l'atelier : XML-TEI (`listPlace` d'abord), RDF ou QuickStatements,
  puis des modèles d'import pour Heurist, nodegoat et Omeka S.

Un lieu non validé n'a pas de `lieu_id` : la colonne reste vide, l'écriture d'origine est là.

## 10. LLM (hors v1)

Décision de l'auteur : aucun LLM au départ ; plus tard, au choix de l'utilisateur, copier-coller
dans son chatbot, clé personnelle ou Ollama. Le LLM **propose**, il n'applique jamais : ses
propositions arrivent dans la file comme celles des règles, avec l'origine `llm`. Le point
d'accroche naturel est un bouton « proposer » sur les clusters faibles. Rien n'est à construire
en v1, sinon garder la place de l'origine `llm` dans le modèle.

## 11. Limites connues

### 11.1 Une même écriture, deux lieux

Une écriture peut désigner deux lieux selon le contexte : « Saint-Fictif » tout court est celui
de l'Ain chez une famille et celui de la Somme chez une autre. Une décision attachée à la seule
valeur ne sait pas les distinguer. L'auteur juge ces cas rares. **Ils sont hors de la v1.**

Piste pour plus tard : des **exceptions de contexte** (pour cette personne, cette famille ou cet
événement, cette écriture désigne tel autre lieu). Elles prennent le pas sur la décision par
valeur, mais ne se transfèrent pas d'un `.gw` à l'autre, faute d'identifiants stables. En v1,
on les contourne en laissant le cluster faible non validé, ou en corrigeant la base dans GeneWeb.

### 11.2 Identifiants de `core`

Les identifiants des tables de `core` (`personne_id`, `evenement_id`…) dépendent de l'ordre du
`.gw` (`exports_design.md` § 4.2). Les décisions n'en dépendent pas (§ 6.3). En revanche, un
export reste lié au fichier dont il est tiré.

## 12. Changements dans le dépôt

- Nouveau membre `atelier/` dans `[tool.uv.workspace]` ; mettre à jour `uv.lock`.
- Retrait de `app/` : `app/docker/geneweb-app`, les pages Streamlit et leur documentation.
- À mettre à jour : `pyproject.toml` racine (description, membres), `run_app.sh` (lancer l'atelier
  ou être supprimé), `.github/workflows/ci.yml` (le build de l'image `geneweb-app` part ; lint et
  tests de l'atelier entrent), `.gitignore` (exceptions `app/**`, ajout de `.superpowers/`),
  `AGENTS.md`, `CLAUDE.md`, `README.md`, `README.en.md`.
- `app/docker/geneweb-server` (le GeneWeb OCaml en conteneur) est **gardé et déplacé**
  (décision de l'auteur), par exemple dans `docker/geneweb-server/` à la racine, avec un
  `docker-compose.yml` réduit à ce seul service. Les chemins de volumes
  (`GENEWEB_BASES_HOST_DIR`, `data/…`) et les règles du `.gitignore` suivent le déplacement.
- Documentation de conception de l'atelier : dans `atelier/doc/`, comme pour `core/doc/`. Ce
  document y sera déplacé à la création du membre.

## 13. Laissé au constructeur

- Les algorithmes et seuils de similarité, et le calcul de la confiance.
- Le schéma SQLite exact du projet et du référentiel, et ses migrations.
- La structure des routes de l'API locale et le découpage du JavaScript.
- Le format JSON exact de l'export du référentiel, versionné dès le départ
  (`"format": "prosopo-gw-atelier/lieux", "version": 1`, sur le modèle de `core`).
- Le choix du port, l'ouverture du navigateur, l'arrêt propre du serveur.
- La découpe en lots du plan d'implémentation.

## 14. Tests

- Fixtures synthétiques : un `.gw` fictif qui couvre les cas décrits par l'auteur (casse, ville
  seule, ville + pays, ville + département + pays, région ancienne, code postal, code INSEE, avec
  et sans complément, ancien nom, abréviations, homonymes dans deux départements).
- Tests unitaires de la décomposition et du regroupement ; tests du rechargement (même `.gw`,
  `.gw` modifié, autre `.gw`) qui vérifient qu'aucune décision n'est à refaire ; tests de
  l'export (le pivot contient les tables de `core` inchangées, plus les ajouts).
- Tests de l'API locale avec le `TestClient` de FastAPI.
- La CI lance lint, mypy et tests de l'atelier. La couverture de `core` n'est pas touchée.
