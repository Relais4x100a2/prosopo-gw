# Prosopo-gw-Atelier

Atelier local de nettoyage pour les bases généalogiques GeneWeb (`.gw`). Il lit une base via le moteur
[`geneweb-py`](https://pypi.org/project/geneweb-py/) et produit un « pivot » importable. Premier thème : les lieux.

**État : alpha (0.1).** Conception : [`doc/design_v1.md`](https://github.com/Relais4x100a2/prosopo-gw/blob/main/atelier/doc/design_v1.md).

## Installation

```bash
uv tool install prosopo-gw-atelier
```

Python 3.11 ou plus récent est requis.

## Lancement

```bash
prosopo-gw-atelier ma_base.gw
```

Le serveur n'écoute que sur `127.0.0.1` ; le navigateur s'ouvre une fois l'atelier prêt. Ctrl+C l'arrête.

| Option | Effet |
| --- | --- |
| `--port N` | port d'écoute (par défaut : un port libre) |
| `--no-browser` | ne pas ouvrir le navigateur |
| `--data-dir DOSSIER` | dossier du référentiel personnel et des projets |

## Ce que fait l'atelier

- Il travaille d'abord sur les lieux : repérage des graphies voisines d'un même lieu, rapprochement avec
  les référentiels publics (COG de l'INSEE, codes postaux), décisions de regroupement ou de rejet.
- Tout reste en local : la base n'est ni envoyée ni modifiée, aucun service distant n'est appelé.
- La sortie est un zip « pivot » de données importables, pas un fichier `.gw` réécrit.
- Un lieu est une chaîne de niveaux, du plus précis au plus large (commune, département, région, pays…).
  Les anciennes communes (fusion, association, délégation) sont des lieux distincts de la commune actuelle.
  De même, une écriture qui nomme un niveau plus précis que la commune (« Wazemmes, Lille ») forme un
  lieu distinct de la commune seule.
- Un référentiel personnel de lieux se constitue au fil des sessions ; il peut être exporté et échangé.
  L'échange JSON est en version 2 ; l'import accepte les versions 1 et 2.

## Où sont les données

Le référentiel (`referentiel.sqlite`) et les projets (`projets/`) vivent dans le dossier de données de
l'utilisateur (via `platformdirs`, par exemple `~/.local/share/prosopo-gw-atelier` sous Linux). La variable
d'environnement `PROSOPO_GW_ATELIER_HOME` ou l'option `--data-dir` le remplacent.

Ouvrir un `referentiel.sqlite` de la v1 le migre vers le schéma à niveaux. Une copie de sauvegarde
`referentiel.v1-AAAAMMJJTHHMMSS.sqlite` (heure UTC) est écrite à côté avant toute modification.

Développement, depuis la racine du monorepo : `uv sync --all-packages --all-extras`.

## Données de référence (COG INSEE et codes postaux)

L'atelier reconnaît les communes, départements, régions et pays à l'aide de deux référentiels
publics, lus hors ligne et embarqués dans le paquet (`src/prosopo_gw_atelier/refdata/data/`,
fichiers CSV compressés et fichier `VERSION` qui donne les millésimes).

### Sources (vérifiées le 7 novembre 2026)

- **Code officiel géographique (COG) de l'INSEE**, millésime 2026 : communes, communes
  associées et déléguées, mouvements des communes depuis 1943, départements, régions, pays.
  Page : <https://www.insee.fr/fr/information/8740218> ; fichiers :
  `https://www.insee.fr/fr/statistiques/fichier/8740222/` (aussi sur data.gouv.fr, jeu
  « Code officiel géographique »).
- **Régions d'avant 2016** : fichier des régions du COG 2015, page
  <https://www.insee.fr/fr/information/2560452>.
- **Base officielle des codes postaux** de La Poste, data.gouv.fr, jeu
  `545b55e1c751df52de9b6045` (<https://www.data.gouv.fr/datasets/545b55e1c751df52de9b6045>),
  fichier `https://data.laposte.fr/data-fair/api/v1/datasets/laposte-hexasmal/raw` ;
  millésime = date de téléchargement.

Les deux sources sont publiées sous **Licence Ouverte 2.0** (Etalab). Toute réutilisation
mentionne la source (INSEE, La Poste) et le millésime.

### Reconstruire les données

Le script `tools/build_refdata.py` ne fait aucune requête réseau : on télécharge d'abord les
fichiers à la main, hors Git (`_local_testdata/` est ignoré) :

- `_local_testdata/refdata/cog-2026/` : `v_commune_2026.csv`, `v_commune_depuis_1943.csv`,
  `v_mvt_commune_2026.csv`, `v_departement_2026.csv`, `v_region_2026.csv`,
  `v_pays_territoire_2026.csv` ;
- `_local_testdata/refdata/cog-2015/` : le fichier des régions du COG 2015 ;
- `_local_testdata/refdata/laposte/` : le CSV de la base officielle des codes postaux.

Puis, depuis la racine du monorepo (adapter le nom des fichiers 2015 et La Poste) :

```bash
uv run --package prosopo-gw-atelier python atelier/tools/build_refdata.py \
  --communes _local_testdata/refdata/cog-2026/v_commune_2026.csv \
  --communes-depuis-1943 _local_testdata/refdata/cog-2026/v_commune_depuis_1943.csv \
  --mouvements _local_testdata/refdata/cog-2026/v_mvt_commune_2026.csv \
  --departements _local_testdata/refdata/cog-2026/v_departement_2026.csv \
  --regions _local_testdata/refdata/cog-2026/v_region_2026.csv \
  --regions-2015 _local_testdata/refdata/cog-2015/reg2015.txt \
  --pays _local_testdata/refdata/cog-2026/v_pays_territoire_2026.csv \
  --codes-postaux _local_testdata/refdata/laposte/laposte_hexasmal.csv \
  --cog-vintage 2026 --postal-vintage 2026-11-07
```

Le script détecte l'encodage (UTF-8 ou Windows-1252/Latin-1) et le séparateur (`,`, `;` ou
tabulation), reconnaît les en-têtes sans tenir compte de la casse ni des accents, et s'arrête
avec un message clair si une colonne attendue manque. Il écrit dans
`src/prosopo_gw_atelier/refdata/data/` (option `--output` pour un autre dossier). Seules les
lignes `COM` du COG sont des communes actuelles ; les communes associées ou déléguées et les
anciens noms tirés des mouvements alimentent l'historique.

Le fichier `historique.csv.gz` a pour colonnes `ancien_nom;ancien_insee;insee_actuel;nature;date_effet`.
La nature vaut `fusion`, `associee`, `deleguee` ou `renommage`. Seules les trois premières créent
une commune historique ; un renommage ajoute un ancien nom à la commune actuelle.

## Sources externes (DicoTopo)

L'atelier peut proposer des noms anciens, des lieux-dits, des hameaux et des écarts à partir de
[DicoTopo](https://dicotopo.cths.fr/) (CTHS, École nationale des chartes). Rien n'est actif au départ et
rien n'est envoyé sans votre action.

- **Activation** : ouvrez l'onglet « Sources ». Téléchargez les départements dont vous avez besoin, un par un
  (environ 52 départements sont couverts ; l'écran indique lesquels). La case « API » autorise en dernier
  recours l'interrogation de l'API DicoTopo pour un article ou un département non téléchargé ; elle est
  décochée par défaut.
- **Cache** : les fichiers `DTxx.xml`, l'index local et la file de recherche vivent dans
  `<dossier de données>/cache/` (`cache/dicotopo/` pour DicoTopo), sous le dossier de `--data-dir`. Le choix
  de la case API est écrit dans `config.json`, au même endroit. Supprimer un département dans l'onglet
  « Sources » retire ses fichiers et son index.
- **Propositions** : une proposition reste un niveau « proposé » tant que vous ne l'avez pas validé ; seuls
  les niveaux validés sont exportés.
- **Licence** : DicoTopo est publié sous licence CC BY-NC-ND 3.0 FR (attribution, pas d'utilisation
  commerciale, pas de modification). Rien de DicoTopo n'est dans ce dépôt, dans les données de test ou dans le
  paquet : les tests utilisent un extrait synthétique. À l'export, un niveau d'origine `dicotopo` porte
  l'identifiant de l'article (`P…`) et, dans `source`, le lien vers sa page publique ; le `LISEZMOI.txt` de
  l'archive cite DicoTopo, la licence et les départements téléchargés avec leur date. Les formes anciennes et les
  commentaires de DicoTopo ne sont jamais exportés.
- **Test ou miroir** : la variable d'environnement `PROSOPO_GW_ATELIER_DICOTOPO_RAW` remplace l'adresse de
  téléchargement des fichiers (avec le marqueur `{dept}`). Elle sert aux tests et à un miroir local.

## Lieux hors de France (GeoNames)

Pour un lieu écrit hors de France, l'atelier peut proposer des niveaux (localité, région, pays) à partir de
[GeoNames](https://www.geonames.org/). Par défaut, chaque pays est en « Garder tel qu'écrit » : rien n'est
proposé et rien n'est envoyé.

- **Écran Pays** : il liste les pays rencontrés dans la base ; seuls ceux que la liste des pays de l'INSEE
  reconnaît y figurent. Un pays sans code ISO (pays historique) reste tel qu'il est écrit. Par pays, le réglage
  « Proposer avec GeoNames » est à activer, puis le fichier du pays se télécharge depuis l'écran ; celui-ci
  affiche la taille exacte avant le premier téléchargement. À titre indicatif, `CA.zip` pèse environ 8 Mo,
  `FR.zip` 7 Mo, `GB.zip` 3,6 Mo et `US.zip` 71 Mo (relevé du 8 novembre 2026). Le réglage d'un pays vaut pour
  tous vos projets.
- **Correction par lieu** : un lieu peut être traité autrement que son pays (proposer ou garder tel qu'écrit).
  « Revenir au réglage du pays » supprime cette correction. Une correction par lieu reste valable si le réglage
  du pays change.
- **Identifiant GeoNames** : il n'est nécessaire que pour le mode API (interrogation en ligne d'un lieu absent
  des fichiers téléchargés) ; les fichiers de pays téléchargés n'en demandent pas. Il est gardé seulement dans le
  `config.json` du dossier de données de l'atelier. Il n'est jamais réaffiché (l'écran dit seulement
  « Identifiant enregistré »), exporté, écrit dans un journal ni placé dans le référentiel.
- **Quota** : l'API gratuite de GeoNames autorise 10 000 requêtes par jour et 1 000 par heure. L'atelier met
  ses tâches API en pause jusqu'à l'heure suivante ou jusqu'à minuit UTC. Si GeoNames refuse l'identifiant
  (compte inconnu, ou service web pas encore activé dans le compte), l'écran Sources le signale et les tâches API
  attendent qu'un identifiant soit de nouveau enregistré, ce qui relance aussi celles qui avaient échoué.
- **Propositions** : un niveau proposé par GeoNames (origine `geonames`) reste « proposé » tant que vous ne
  l'avez pas validé ; un niveau écrit que GeoNames ne connaît pas est conservé tel quel.
- **Licence et export** : GeoNames est publié sous licence CC BY 4.0. Rien de GeoNames n'est dans ce dépôt ni
  dans le paquet ; les tests utilisent de petits fichiers synthétiques. À l'export, un niveau d'origine
  `geonames` porte son `geonameid` dans `identifiant`, `GeoNames <date>` dans `source` et ses coordonnées ; les
  coordonnées de `lieux` sont celles du niveau le plus précis qui en a. Le `LISEZMOI.txt` de l'archive cite
  GeoNames, la licence et les pays téléchargés avec leur date seulement si un niveau `geonames` est exporté.
- **Test ou miroir** : la variable `PROSOPO_GW_ATELIER_GEONAMES_DUMP` remplace l'adresse de téléchargement
  (URL http(s) terminée par `/`).

## Export

L'export pivot contient les tables de `geneweb-py`, puis `lieux`, `niveaux_lieux` et `ecritures_lieux`.
`niveaux_lieux` a une ligne par niveau validé : `lieu_id`, `rang` (0 = le plus précis), `nom`, `nom_ecrit`,
`type`, `nature`, `identifiant`, `source`, `debut`, `fin`, `latitude`, `longitude`, `origine`. Les niveaux
seulement proposés ne sont pas exportés. `lieux` en donne la vue française (commune, département, région,
pays, ancienne commune et son code INSEE) et le `libelle`. Le dictionnaire de l'export décrit chaque colonne.
`precisions_occurrences` donne, pour chaque occurrence d'un lieu de Paris, Lyon ou Marseille,
l'arrondissement (et le quartier de Paris) qu'elle désigne, avec la période, l'indice et le statut
(`applique`, `conflit`, `incertain`, `ambigu`). Une ligne par candidat quand rien n'est tranché.

## Arrondissements et précisions

Une écriture qui nomme un arrondissement (« Paris 7e », « 75007 Paris », « Lyon, 3e arr. ») forme un
niveau et un lieu à part de la ville seule. Les numéros d'avant 1860 (12 anciens arrondissements de
Paris) et d'après sont distingués selon la date de l'acte.

L'onglet **Précisions** liste les occurrences dont l'arrondissement n'est pas tranché :
- **conflit** : le code, le numéro et la rue désignent deux arrondissements ;
- **incertaine** : la date, ou l'intervalle d'une date approximative, touche 1859-1861
  (annexion de 1860), donc la numérotation d'avant ou d'après ne peut pas être choisie ;
  ou bien le code désigne l'arrondissement actuel sur une occurrence d'avant 1860, ou
  l'arrondissement de Lyon ou de Marseille n'existait pas encore à cette date ;
- **ambiguë** : une rue traverse plusieurs arrondissements.

Rien n'est choisi à votre place. Vous choisissez un candidat, ou « aucun arrondissement », et la
décision est inscrite au journal ; elle peut être annulée, ou retirée avec « Revenir au calcul »
(même après un redémarrage). Pour Lyon et Marseille, seuls le code et le
numéro comptent ; pour Paris, la rue lue dans le complément (« 12 rue Saint-Honoré ») s'ajoute.

La table des rues de Paris est livrée dans le paquet (`refdata/paris/`). Elle est dérivée de
données de la Ville de Paris et du consortium ALPAGE, sous licence **ODbL 1.0**. Les exports
reprennent la note d'attribution dans leur `LISEZMOI.txt`. Détails : `doc/design_v1.md` § 6.5 et
`docs/superpowers/specs/2026-11-08-atelier-lieux-niveaux-design.md` § 6.

## Publication (mainteneurs)

La publication sur PyPI part d'une étiquette Git (`.github/workflows/release.yml`) :
`core-vX.Y.Z` publie `geneweb-py`, `atelier-vX.Y.Z` publie `prosopo-gw-atelier`. Le flux
rejoue d'abord les tests du paquet étiqueté, puis construit et publie.

L'atelier dépend de `geneweb-py` : quand une version de l'atelier exige une nouvelle version
du moteur, poser et laisser aboutir **`core-vX.Y.Z` avant `atelier-vX.Y.Z`**. Sinon
`pip install prosopo-gw-atelier` échoue faute de trouver la version de `geneweb-py` demandée.
