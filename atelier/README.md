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
- Un référentiel personnel de lieux se constitue au fil des sessions ; il peut être exporté et échangé.

## Où sont les données

Le référentiel (`referentiel.sqlite`) et les projets (`projets/`) vivent dans le dossier de données de
l'utilisateur (via `platformdirs`, par exemple `~/.local/share/prosopo-gw-atelier` sous Linux). La variable
d'environnement `PROSOPO_GW_ATELIER_HOME` ou l'option `--data-dir` le remplacent.

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
anciens noms tirés des mouvements alimentent l'historique (recherche par ancien nom).
