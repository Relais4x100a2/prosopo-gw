# Atelier : lieux à niveaux, communes historiques, arrondissements et sources externes

Conception, 8 novembre 2026. Fait suite à l'essai de l'atelier v1 (`atelier/doc/design_v1.md`) sur
une base réelle. Ce document **modifie** le § 6 (étape des lieux), le § 7 (écran), le § 8
(enrichissements) et le § 9 (pivot) de la conception v1 ; le reste de la v1 vaut toujours.

Les décisions de l'auteur sont marquées **(décision de l'auteur)**. Les choix faits par le
rédacteur sans validation explicite sont marqués **(choix de conception)** : l'auteur peut les
contester à la relecture.

## 1. Intention

L'essai de la v1 sur une base réelle a montré trois pertes d'information, toutes dues au même
défaut : chaque écriture est rangée dans des cases françaises fixes (commune, code INSEE,
département, région, pays, ancien nom).

1. **Arrondissements perdus.** Paris, Lyon et Marseille sont réduits à la commune. Or
   l'arrondissement est souvent l'information utile, et son découpage a changé : Paris a eu
   12 arrondissements jusqu'en 1859, puis 20 depuis 1860, avec une autre numérotation.
2. **Communes fusionnées écrasées.** Une ancienne commune (Marconne, aujourd'hui dans
   Hesdin-la-Forêt) est fondue dans sa commune actuelle, avec un seul champ « ancien nom ». Deux
   anciennes communes d'une même commune actuelle se retrouvent mêlées.
3. **Niveaux étrangers supprimés.** `Winnipeg, , , Manitoba, Canada` devient Winnipeg, Canada.
   `Storrington, , East Sussex, England, Royaume-Uni` devient Storrington, Royaume-Uni.

Le principe qui en découle : **l'atelier ne jette jamais un niveau écrit**. Il le garde, le
type quand il peut, et propose des compléments tirés de référentiels, que l'utilisateur valide.

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs**
- Un modèle de lieu à **niveaux ordonnés**, du plus précis au pays, sans nombre imposé.
- Les **communes historiques** comme lieux distincts, rattachés à leur commune actuelle.
- Les **arrondissements** de Paris (12 anciens et 20 actuels), Lyon et Marseille, datés.
- Les **lieux étrangers** gardés avec tous leurs niveaux ; typage et compléments par GeoNames,
  au choix de l'utilisateur, pays par pays.
- **DicoTopo** pour les noms anciens et les lieux-dits français.
- Une architecture de **sources externes** qui tient sur une base de 3 millions de personnes.

**Non-objectifs (pour cette version)**
- Convertir un pays historique (Prusse, Bohême, Russie) vers le pays actuel : il reste tel
  qu'écrit **(décision de l'auteur)**.
- Les fusions de communes antérieures à 1943 que ni le COG ni DicoTopo ne couvrent, les
  paroisses, la base Cassini, Wikidata : plus tard.
- Les arrondissements d'autres villes, les sections révolutionnaires de Paris (1790-1795).
- Les exceptions de contexte de la v1 (§ 11.1) restent hors champ, sauf la datation des
  arrondissements par occurrence (§ 6.3), qui est un cas particulier traité ici.

**Anti-objectifs**
- **Écraser ce qui est écrit.** Une proposition d'un référentiel s'affiche à côté de l'écriture,
  jamais à sa place, et n'est appliquée qu'après validation.
- **Faire de DicoTopo l'autorité sur la commune actuelle.** DicoTopo prime sur les noms anciens,
  pas sur le dernier nom ni le code INSEE actuel, qui viennent du COG **(décision de l'auteur)**.
- **Mettre une donnée sous licence restrictive dans le dépôt ou le paquet** (DicoTopo).
- **Envoyer au réseau autre chose que des noms de lieux**, ou sans que l'utilisateur ait activé
  la source.
- **Interroger une API lieu par lieu sur une grosse base** quand une copie locale est possible.

## 3. Contraintes

- Toutes les contraintes de la v1 (§ 4) : dépôt public, aucune donnée réelle, `uv`, `core` non
  modifié, Python ≥ 3.11, mypy strict.
- **L'atelier tourne en local mais peut consommer des services en ligne** quand une donnée ne
  peut pas être livrée avec lui **(décision de l'auteur)**. Chaque source en ligne s'active
  explicitement ; seuls des noms de lieux, des codes et des identifiants partent sur le réseau.
- **Volumétrie** : de 20 000 à 3 millions de personnes (base Pierfit). On vise quelques dizaines
  à quelques centaines de milliers d'écritures distinctes. Les traitements de masse se font sur
  des index locaux ; l'API en ligne n'est qu'un dernier recours.
- **Licences**

| Source | Licence | Où elle vit |
|---|---|---|
| COG INSEE, codes postaux La Poste | Licence Ouverte 2.0 | dans le paquet (déjà en v1) |
| Voies de Paris actuelles et caduques (Ville de Paris) | ODbL | table dérivée dans le paquet, dossier à part |
| Quartiers Vasserot 1790-1860 (ALPAGE) | ODbL | idem |
| Rues Vasserot 1810-1836 (ALPAGE) | ODbL (à vérifier : mêmes conditions que les quartiers) | idem |
| Réseaux de rues Verniquet et Jacoubet (GeoHistoricalData, Harvard Dataverse doi:10.7910/DVN/CCESX4) | CC0 | idem |
| GeoNames | CC BY 4.0 (à vérifier par le constructeur) | téléchargé à la demande |
| DicoTopo (CTHS, École nationale des chartes) | CC BY-NC-ND 3.0 FR | téléchargé à la demande, index privé |

## 4. Le modèle de lieu à niveaux

### 4.1 Niveaux

Un **lieu** retenu est une chaîne de **niveaux**, du plus précis au plus large **(choix de
conception, validé dans son principe par l'auteur)**. Chaque niveau porte :

| Attribut | Sens |
|---|---|
| `rang` | 0 pour le niveau le plus précis, puis croissant jusqu'au pays |
| `nom` | le nom retenu (typographie nettoyée : espaces, casse) |
| `nom_ecrit` | le nom tel qu'écrit, quand il diffère du nom retenu |
| `type` | voir § 4.2 ; vide si inconnu |
| `identifiant` | code INSEE, identifiant d'arrondissement (§ 6.2), `P…` DicoTopo, identifiant GeoNames… |
| `debut`, `fin` | période de validité, quand elle est connue (année ou date ISO) |
| `latitude`, `longitude` | coordonnées WGS 84, quand une source les donne (GeoNames, DicoTopo, données de Paris), à valider comme le reste **(décision de l'auteur : dans cette version)** |
| `origine` | `ecrit`, `regle`, `manuel`, `insee`, `paris`, `dicotopo`, `geonames`, plus tard `llm` |
| `statut` | `valide` ou `propose` |

Exemples :

| Écriture | Niveaux (rang : nom, type) |
|---|---|
| `Storrington, , East Sussex, England, Royaume-Uni` | 0 Storrington, localité · 1 East Sussex, comté · 2 England, nation constitutive · 3 Royaume-Uni, pays |
| `Winnipeg, , , Manitoba, Canada` | 0 Winnipeg, localité · 1 Manitoba, province · 2 Canada, pays |
| `Marconne, Pas-de-Calais` | 0 Marconne, commune historique · 1 Hesdin-la-Forêt, commune · 2 Pas-de-Calais, département · 3 Hauts-de-France, région · 4 France, pays |
| `Paris 7e` | 0 7e arrondissement, arrondissement (période résolue par occurrence, § 6.3) · 1 Paris, commune · … · France, pays |

Les champs vides d'une écriture GeneWeb (`, ,`) sont ignorés ; **tout champ rempli devient un
niveau** **(décision de l'auteur)**. Un niveau écrit que l'atelier ne reconnaît pas reste un
niveau sans type.

### 4.2 Types

Une liste fermée pour la France (`lieu_dit`, `quartier`, `arrondissement`, `commune_historique`,
`commune`, `departement`, `region`, `ancienne_region`, `pays`) et une liste ouverte pour
l'étranger (`localite`, `comte`, `province`, `etat`, `nation_constitutive`, `oblast`…), que
l'utilisateur peut compléter. Le constructeur fixe la liste initiale **(choix de conception)**.

### 4.3 La France garde ses cases, comme vue

Pour un lieu français, les cases de la v1 (commune, code INSEE, code postal, département, région,
pays) restent affichées et exportées : elles sont **calculées à partir des niveaux**, pas
stockées à part **(choix de conception)**. Le champ `ancien_nom` disparaît, remplacé par le
niveau `commune_historique` (§ 5).

Le **code postal** n'est pas un niveau : c'est un attribut du lieu, comme en v1.

### 4.4 Regroupement de lieux étrangers

Deux écritures étrangères peuvent aller dans le même cluster si leurs niveaux ne se
contredisent pas (« Storrington, Royaume-Uni » et « Storrington, , East Sussex, England,
Royaume-Uni ») ; la forme retenue proposée est alors la plus complète. Si deux niveaux de même
rang se contredisent (East Sussex et West Sussex), les écritures forment deux clusters, marqués
de confiance faible pour que l'utilisateur vérifie **(choix de conception)**.

### 4.5 Ce qui ne change pas

La clé d'une décision reste l'écriture sans complément (v1 § 6.3). Le complément reste un
attribut de l'occurrence. Le regroupement en clusters, l'écran liste + détail, le référentiel
personnel hors projet, son journal et son export JSON gardent leur fonctionnement.

## 5. Communes historiques (France)

**Décision de l'auteur** : une ancienne commune est un **lieu distinct**, rattaché à sa commune
actuelle. Exemple : Marconne, lieu distinct, avec Hesdin-la-Forêt comme commune actuelle.

- Elle a un niveau 0 de type `commune_historique`, avec son **ancien code INSEE** et ses dates
  (`fin` = date d'effet de la fusion), puis les niveaux de sa commune actuelle.
- Deux écritures de deux anciennes communes ne sont **plus** regroupées sous la commune actuelle :
  Marconne et Hesdin (ancienne commune) sont deux clusters, chacun rattaché à Hesdin-la-Forêt
  **(choix de conception)**. Une écriture de la commune actuelle elle-même (« Hesdin-la-Forêt »)
  forme un troisième cluster.
- **Source** : l'historique du COG (fusions, communes associées et déléguées, changements de
  nom depuis 1943), déjà embarqué. Le constructeur étend `historique.csv.gz` pour garder l'ancien
  code INSEE, le type d'événement et la date.
- **Cas ambigu** : un nom actuel qui a aussi été le nom d'une ancienne commune (Hesdin) produit
  deux candidats ; le cluster est marqué de confiance moyenne et l'utilisateur tranche.
- **Simple changement de nom** (même territoire, même code INSEE) : ce n'est **pas** un lieu
  distinct. L'ancien nom reconnaît la commune, il est gardé dans `nom_ecrit` du niveau commune,
  et le code INSEE reste la clé forte du regroupement **(choix de conception)**. Seules une
  fusion, une association ou une délégation créent une `commune_historique`.
- **Communes associées et déléguées** (Lomme, associée à Lille) : même traitement, type
  `commune_historique` avec son statut (associée, déléguée) dans le niveau
  **(choix de conception)**.
- **Communes annexées par Paris en 1860** (Belleville, Passy, Vaugirard…) et autres fusions
  antérieures à 1943 : le COG ne les couvre pas. Pour Paris, la table parisienne (§ 6) en donne
  la liste ; ailleurs, DicoTopo (§ 7) peut les reconnaître dans les départements qu'il couvre.

## 6. Arrondissements de Paris, Lyon et Marseille

### 6.1 Ce qui est couvert (décision de l'auteur : les 12 anciens dès cette version)

| Ville | Découpages | Codes actuels |
|---|---|---|
| Paris | 12 arrondissements (1795-1859), 48 quartiers ; 20 arrondissements (depuis 1860), 80 quartiers | INSEE 75101-75120, postaux 75001-75020 et 75116 |
| Lyon | arrondissements créés et redécoupés entre 1852 et 1964 | INSEE 69381-69389, postaux 69001-69009 |
| Marseille | 16 arrondissements (depuis 1946) | INSEE 13201-13216, postaux 13001-13016 |

Le constructeur vérifie les dates de création et de redécoupage de Lyon et de Marseille avant de
les inscrire.

Un arrondissement est un **niveau** du lieu (§ 4), de type `arrondissement`, au-dessus duquel
vient la commune. Pour Paris, un niveau `quartier` peut s'ajouter.

### 6.2 Identifiants

Les arrondissements actuels ont leur code INSEE. Les anciens arrondissements de Paris reçoivent
un identifiant stable propre à l'atelier, par exemple `paris-1795-07` pour l'ancien 7e
**(choix de conception)** ; leurs quartiers, l'identifiant ALPAGE.

### 6.3 Déduction, et datation par occurrence

Ordre des indices **(décision de l'auteur)** :
1. **le code** : code INSEE ou postal d'arrondissement (750xx, 751xx, 690xx, 693xx, 130xx,
   132xx). Il désigne un arrondissement actuel, donc valable après 1860 à Paris ;
2. **le numéro écrit** (« 7e », « 7ème », « VIIe arr. », « 7e arrondissement »), interprété
   selon la date de l'acte ;
3. **le nom de la rue**, actuel ou ancien, croisé avec la date : voies de Paris (actuelles et
   caduques) après 1860 ; réseaux Verniquet et Jacoubet croisés avec les quartiers Vasserot avant
   1860.

**Lieu distinct.** Une écriture qui porte un arrondissement (« Paris 7e », « 69001 Lyon ») forme
un cluster et un `lieu_id` **distincts** de la ville seule, comme Marconne l'est de
Hesdin-la-Forêt. Le code INSEE de la commune n'est donc plus une clé forte qui fusionne
« Paris 7e » et « Paris » ; le code d'arrondissement l'est. Le niveau 0 d'un « 7e » sans période
a pour identifiant le numéro seul (`paris-07`), la période étant donnée par occurrence
**(choix de conception)**.

Le même numéro désigne deux arrondissements différents selon la date (l'ancien 7e n'est pas le
7e actuel). L'écriture « Paris 7e » reste **une** décision (v1 § 6.3), mais la **période** de
l'arrondissement se résout **par occurrence**, avec la date de l'événement **(choix de
conception)** :

- le lieu retenu porte le numéro et la ville ;
- chaque occurrence reçoit une **précision** : l'arrondissement daté (et le quartier quand la rue
  le donne), avec l'indice qui l'a produite ;
- la rue vient du **complément** de l'occurrence (v1 § 6.1) ; une écriture « Paris » sans numéro
  peut ainsi recevoir un arrondissement par occurrence.

**Où vivent les précisions** : dans le **référentiel personnel**, avec une clé par valeur
(écriture + complément + période), comme les décisions de la v1. Une précision tranchée se
réapplique donc à tout `.gw` rechargé et part dans l'export JSON du référentiel. Elle ne dépend
jamais des identifiants de `core` (v1 § 11.2) ; la table `precisions_occurrences` de l'export
est calculée à la volée **(choix de conception)**.

Une occurrence **sans date** garde le numéro sans période. Une occurrence datée de l'année de
transition (1860 pour Paris) est marquée incertaine.

**Contradictions** : quand deux indices désignent deux arrondissements (code postal du 7e, rue
du 15e), la précision est marquée **en conflit**, avec les deux propositions, et rien n'est
tranché en silence **(décision de l'auteur)**.

Les précisions sans conflit sont appliquées d'office, avec leur indice visible ; les conflits et
les incertaines forment une liste à traiter (§ 9) **(choix de conception)**.

### 6.4 La table parisienne

Le constructeur l'établit **une fois**, dans `atelier/tools/`, à partir des sources du § 3 :
`rue normalisée + période → arrondissement, quartier`, plus la liste des communes annexées en
1860 et la correspondance entre anciens et nouveaux arrondissements quand elle est univoque.

- **Sources avant 1860, par API (scénario retenu)** : deux couches ALPAGE servies par un
  service ArcGIS public et interrogeables en GeoJSON : les rues Vasserot 1810-1836
  (`VasserotRoads_1810to1836/FeatureServer/1`, 4 368 tronçons, nom complet de la voie) et les
  quartiers Vasserot (`VasserotQuartiers_1790to1860/FeatureServer/1`, 48 quartiers avec leur
  arrondissement). Les deux couches viennent du même projet, donc du même calage. L'outil
  rattache chaque tronçon au quartier qui contient son milieu, **en Python pur** (point dans un
  polygone), sans bibliothèque SIG. Le compte ArcGIS qui sert ces couches n'est pas celui
  d'ALPAGE : l'outil enregistre la date d'extraction, et la table produite est figée dans le
  paquet, donc l'atelier n'en dépend pas à l'exécution. Verniquet et Jacoubet (CC0) ne sont qu'un
  complément facultatif (noms de rues de 1784-1791) **(choix de conception)**.
- **Repli** : si ces couches deviennent inaccessibles avant la construction, l'étape 2 sort avec
  le code et le numéro seulement, et les rues et quartiers d'avant 1860 passent à une étape
  suivante **(choix de conception)**.
- Le **croisement géographique** se fait **dans l'outil de construction seulement**. L'atelier ne
  lit qu'une table, sans dépendance SIG.
- La table est livrée dans le paquet, **dans un dossier à part avec sa licence ODbL et sa note
  d'attribution** (Ville de Paris, consortium ALPAGE et auteurs, GeoHistoricalData), reprise
  dans le `LISEZMOI` de l'export.
- Une rue qui a traversé plusieurs arrondissements ou quartiers donne plusieurs candidats : la
  précision est alors marquée ambiguë, pas devinée.
- Les sources sont téléchargées par l'outil, jamais versionnées brutes.

Lyon et Marseille n'utilisent que le code et le numéro, pas la rue **(choix de conception)**.

## 7. DicoTopo

**Rôle.** DicoTopo prime sur les **noms anciens** : formes anciennes d'une commune, lieux-dits,
hameaux, écarts, anciennes paroisses **(décision de l'auteur)**. Il propose un niveau
`lieu_dit` sous une commune, ou reconnaît un nom ancien d'une commune.

**Codes INSEE de 2011.** DicoTopo localise ses articles avec le code INSEE de 2011. L'atelier les
**ramène toujours à la commune actuelle** par l'historique du COG ; l'ancienne commune de 2011,
si elle a disparu depuis, devient un niveau `commune_historique` (§ 5). DicoTopo ne fixe jamais
la commune actuelle **(décision de l'auteur)**.

**Accès.**
- **Copie locale** : les fichiers `data/DTxx/DTxx.xml` du dépôt GitHub `chartes/dico-topo`, un
  par département couvert. Ils sont téléchargés **à la demande de l'utilisateur**, département par
  département, dans le cache commun (§ 10), puis indexés localement (formes normalisées → article).
- **API** (`https://dicotopo.cths.fr/api/1.0/`) : en dernier recours seulement, pour un article
  précis ou un département non téléchargé. La pagination de la collection `/places` renvoie une
  erreur 500 : on n'aspire pas la base par l'API.

**Licence (CC BY-NC-ND 3.0 FR).** Rien de DicoTopo dans le dépôt, les fixtures de tests
publiées ou le paquet. Les tests utilisent un extrait **synthétique** au même format XML. À
l'export, un niveau d'origine `dicotopo` porte l'identifiant `P…`, le lien vers l'article et la
mention de la source ; le nom du niveau est celui que l'utilisateur a validé. Les formes
anciennes et les commentaires de DicoTopo ne sont pas exportés **(choix de conception)**.

**Couverture.** 52 départements environ. L'écran Sources (§ 9) indique lesquels.

## 8. Lieux étrangers et GeoNames

**Par défaut, l'atelier garde ce qui est écrit** : les niveaux dans l'ordre, nettoyés dans leur
typographie seulement. Le **pays** est normalisé comme en v1 **(décision de l'auteur)**.

**GeoNames est une option, choisie pays par pays, corrigeable lieu par lieu (décision de
l'auteur).**
- Un écran liste les pays présents dans le projet, avec leur nombre d'écritures, et pour chacun
  le choix : « garder tel qu'écrit » ou « proposer avec GeoNames ».
- Ce réglage vit dans le **référentiel personnel** et suit l'utilisateur d'un projet à l'autre
  **(choix de conception)**.
- Sur un lieu, l'utilisateur peut faire l'inverse du réglage de son pays. Cette correction
  **reste valable** si le réglage du pays change ensuite **(décision de l'auteur)**.

**Ce que GeoNames propose**, à valider, source affichée :
- le **type** de chaque niveau (Manitoba : province ; East Sussex : comté) ;
- les **niveaux manquants** (une ville écrite avec le seul pays reçoit sa province) ;
- l'**identifiant GeoNames** de la localité et des niveaux.

En cas de désaccord, ce qui est écrit reste affiché à côté de la proposition ; rien n'est écrasé.
Un niveau écrit que GeoNames ne connaît pas (nom historique) reste tel quel.

**Accès.**
- **Fichiers** : par pays (`<CC>.zip`) ou les localités de plus de 500 habitants
  (`cities500.zip`), plus les tables des niveaux administratifs (`admin1CodesASCII.txt`,
  `admin2Codes.txt`) et les pays (`countryInfo.txt`). Téléchargés à la demande dans le cache
  commun ; un pays passé à « proposer avec GeoNames » déclenche le téléchargement de son fichier
  **(choix de conception)**. Le constructeur vérifie les noms de fichiers, la licence et les
  tailles.
- **API** : dernier recours, pour un lieu absent des fichiers, et seulement si l'utilisateur a
  saisi son **identifiant GeoNames** (compte gratuit, plafonds horaires et journaliers). Cet
  identifiant est stocké dans la configuration locale de l'utilisateur, jamais dans le dépôt ni
  dans un export.

**Limite.** GeoNames décrit la géographie actuelle : Prusse ou Bohême restent tels qu'écrits.

## 9. Écran

L'écran liste + détail de la v1 est gardé. Ce qui change :

- **Détail d'un cluster** : la forme retenue s'affiche comme une **chaîne de niveaux** modifiable
  (ajouter, retirer, renommer, typer, réordonner un niveau). Pour la France, les cases calculées
  restent visibles au-dessus. Chaque niveau montre son origine ; une proposition (`propose`)
  s'affiche avec sa source et deux actions, accepter ou refuser, à côté du niveau écrit.
- **Communes historiques** : le cluster montre la commune historique et sa commune actuelle.
- **Précisions par occurrence** (arrondissements) : un onglet ou une liste des précisions en
  conflit, incertaines ou ambiguës, regroupées par écriture + complément + période pour qu'un
  seul geste en traite plusieurs **(choix de conception)**.
- **Écran Pays** : le réglage GeoNames pays par pays (§ 8).
- **Écran Sources** : DicoTopo (départements téléchargés, à télécharger), GeoNames (pays
  téléchargés, identifiant API), état de la file de fond (§ 10) avec progression et erreurs, et
  les attributions.

La disposition exacte est à valider par un prototype cliquable, comme pour la v1
**(choix de conception)**.

## 10. Architecture des sources

**(Approche validée par l'auteur)**

- **Référentiels embarqués d'abord** : COG, codes postaux, table parisienne. Ils traitent tout
  ce qu'ils peuvent, sans réseau, au chargement du projet.
- **Une interface par source**, avec deux modes, local ou API, derrière les mêmes appels :
  chercher des candidats pour un nom de niveau (avec son contexte : niveaux voisins, pays,
  département), lire un article par identifiant. Elle renvoie identifiant, nom, type, niveaux
  parents, période, et la source.
- **Un cache persistant commun à tous les projets**, dans le dossier de données de l'utilisateur
  (à côté du référentiel personnel) : fichiers téléchargés, index construits, réponses d'API.
  Il est réutilisé d'un projet à l'autre et se vide depuis l'écran Sources.
- **Une file de tâches de fond**, avec :
  - une **priorité** : les clusters à beaucoup d'occurrences d'abord, puis ceux que
    l'utilisateur ouvre ;
  - une **limite de débit par source** (GeoNames : plafonds du compte ; DicoTopo : modéré) ;
  - la **reprise** après redémarrage de l'atelier ;
  - des résultats qui arrivent comme **propositions** dans le référentiel, jamais comme
    décisions.
- **Volumétrie** : sur une grosse base, l'API ne sert qu'aux écritures que les index locaux n'ont
  pas résolues. L'écran ne doit pas reconstruire toute la liste à chaque vue (point déjà relevé
  dans `docs/reflexions/points-ouverts.md` § 5).

## 11. Export (pivot)

Le pivot de la v1 change ainsi **(choix de conception)** :

- **`lieux`** : garde `lieu_id` et les colonnes calculées pour la France (`commune`,
  `code_insee`, `code_postal`, `departement`, `region`, `pays`) avec leur `…_origine`.
  `ancien_nom` est remplacé par `commune_historique` et `code_insee_historique`. `latitude` et
`longitude` reprennent celles du niveau le plus précis qui en a. Une colonne
  `libelle` donne la chaîne complète des niveaux, lisible.
- **`niveaux_lieux`** (nouvelle) : `lieu_id`, `rang`, `nom`, `nom_ecrit`, `type`,
  `identifiant`, `source`, `debut`, `fin`, `latitude`, `longitude`, `origine`. Seuls les niveaux validés sont exportés.
  Ainsi un lieu à trois niveaux comme un lieu à six restent importables.
- **`precisions_occurrences`** (nouvelle) : `table`, `ligne_id`, `colonne`, `lieu_id`,
  `arrondissement`, `arrondissement_id`, `quartier`, `quartier_id`, `indice`, `statut`
  (`applique`, `conflit`, `incertain`, `ambigu`).
- **`LISEZMOI.txt`** : les attributions de chaque source utilisée, avec millésime ou date de
  téléchargement, et le rappel des licences (ODbL pour la table parisienne, CC BY pour GeoNames,
  CC BY-NC-ND pour DicoTopo).
- **Export JSON du référentiel** : `"version": 2`. L'import accepte toujours la version 1.

## 12. Reprise des projets et référentiels v1

**(Choix de conception)**
- À l'ouverture, un référentiel v1 est **migré** : chaque lieu reçoit ses niveaux à partir de ses
  champs (commune, département, région, pays), avec la même origine.
- Les **décisions déjà validées sont reprises telles quelles** : aucun rattachement d'écriture
  ne change en silence.
- Les informations nouvelles deviennent des **propositions** : un lieu v1 dont `ancien_nom` est
  rempli reçoit la proposition de devenir (ou de produire) une commune historique distincte ;
  un lieu de Paris, Lyon ou Marseille reçoit les arrondissements déduits ; un lieu étranger
  reçoit les niveaux écrits qui avaient été perdus.
- La migration est inscrite au journal et précédée d'une copie de sauvegarde du référentiel.

## 13. Étapes livrables

Chaque étape est utilisable seule, testée, et peut être publiée **(choix de conception)** :

1. **Modèle à niveaux et communes historiques** : niveaux, lieux étrangers gardés tels
   qu'écrits, communes historiques depuis le COG, migration v1, export (`niveaux_lieux`,
   `lieux` modifiée). Corrige les trois pertes pour tout ce que le COG couvre.
2. **Arrondissements** : Paris (anciens et actuels, rues, quartiers), Lyon et Marseille ; table
   parisienne et son outil de construction ; précisions par occurrence.
3. **DicoTopo** : cache commun, file de fond, interface de source, téléchargement et index local,
   écran Sources.
4. **GeoNames** : écran Pays, fichiers par pays, API en dernier recours.

## 14. Laissé au constructeur

- La liste initiale des types de niveaux (§ 4.2) et leurs libellés.
- Le schéma SQLite des niveaux, des précisions et de la file, et la migration.
- Les règles exactes de reconnaissance d'un numéro d'arrondissement écrit.
- La normalisation des noms de rues (articles, « rue de la », abréviations).
- Le format de l'index local DicoTopo et des index GeoNames, et l'emplacement exact du cache.
- La technique de la file de fond (fil d'exécution, processus), tant qu'elle reprend après
  redémarrage et respecte les limites de débit.
- Le découpage en lots du plan d'implémentation, dans l'ordre du § 13.

## 15. Tests

- Fixtures **synthétiques** uniquement. Les noms de communes, de rues et de pays réels sont
  permis (ce ne sont pas des données de personnes), les noms de personnes non.
- Les trois cas de l'essai, reproduits avec des personnes fictives : `Winnipeg, , , Manitoba,
  Canada` garde Manitoba ; `Storrington, , East Sussex, England, Royaume-Uni` garde ses quatre
  niveaux ; Marconne et Hesdin restent deux lieux rattachés à Hesdin-la-Forêt.
- Les tests de la v1 qui supposent l'ancien comportement sont **revus** :
  `test_postal_code_of_municipal_arrondissement_maps_to_commune` (69001 doit donner le 1er
  arrondissement de Lyon, en plus de la commune) et `test_merged_commune` (Lomme devient une
  commune historique de Lille).
- Arrondissements : le même « 7e » en 1850 et en 1870 ; code postal et rue en conflit ;
  occurrence sans date ; rue qui a changé d'arrondissement.
- DicoTopo : un extrait XML synthétique ; code INSEE 2011 d'une commune fusionnée depuis,
  ramené à la commune actuelle ; aucune requête réseau dans les tests.
- GeoNames : de petits fichiers synthétiques au format GeoNames ; réglage par pays et correction
  par lieu qui survit au changement du réglage.
- Migration : un référentiel v1 synthétique ouvert sans perte de décision.
- Export : `niveaux_lieux` et `precisions_occurrences` présents ; attributions dans le
  `LISEZMOI`.
