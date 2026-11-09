# Points ouverts (8 novembre 2026)

Ce document rassemble les points reportés pendant les chantiers de novembre 2026 : organisations
candidates, refonte des exports, atelier v1 (lieux). Ils figuraient dans les journaux de travail
locaux, non versionnés, qui ont été supprimés ensuite. Les comptes tirés d'une base réelle sont
donnés en ordre de grandeur seulement.

La réflexion de fond sur les étapes suivantes de l'atelier (notes, profession de l'état civil,
sources, événements « Autre », organisations) reste dans :

- `docs/reflexions/2026-11-06-atelier-nettoyage.md` (§ 5.4 conventions, § 9 décisions, § 10 questions) ;
- `core/doc/organizations_candidates_design.md` (§ 7 voies de validation, § 8 chantier B) ;
- `core/doc/exports_design.md` (§ 9 sources multiples, pistes de sources, XML-TEI) ;
- `atelier/doc/design_v1.md` (pivot et étape lieux).

## 1. Événements « Autre » et organisations

- **Étiquettes « Autre » de type recensement ou domicile.** Sur la base réelle, environ 170 liens
  tombent dans le cas « à déterminer » à cause de leur complément de lieu. Aucun n'atteint deux
  personnes, donc aucun ne devient candidate, mais ils sont créés comme organisations. Les mots
  ignorés (recensement, domicile par défaut) traitent une partie du problème ; la règle de création
  reste à revoir.
- **Événement « Autre » compté deux fois.** Un lien sans `source_event_id` (issu d'un ancien
  `.org.json`) peut apparaître à la fois dans « reste à classer » et comme membre d'une candidate.
- **Ancien `.org.json` puis ré-inférence** (usage en bibliothèque seulement) : un lien en double
  par événement. Correctif envisagé : sans identifiant d'événement, comparer sur la clé sans l'id.
- **Organisations issues d'un compagnon** jamais recalculées après une modification.
- **Fusion des propositions** : `register()` ne remplace jamais le type, `named_from` ou le
  déclencheur quand une proposition plus forte arrive en second (le type peut rester « autre »).
- **Mot d'établissement dans une étiquette écartée** (cas « à déterminer ») : la spécification ne
  dit pas s'il doit fixer le type.
- **Préfixe `intern`** qui capte « Internat ».

## 2. Profession de l'état civil et notes

- **Note d'un événement profession et attribut profession** : quand l'événement porte une ville, on
  obtient deux organisations (l'une avec la ville, l'autre sans) pour la même personne. Impact mesuré
  faible sur la base réelle.
- **Pistes tirées des notes** (table `pistes`) :
  - forme juridique jugée « forte » dès que le mot précédent a une majuscule (début de phrase) ;
  - `piste_id` dépend du début de la fenêtre fusionnée : ignorer un mot ou modifier le début d'une
    note change les identifiants ;
  - la fixture du zip n'a pas de note de famille (jointure `famille_id` et rendu JSON non testés) ;
  - `_widen` balaie sans borne un texte très long sans espace.
- Les pistes restent à valider par l'utilisateur : pas d'attrape-tout automatique (faux positifs
  « en compagnie de », adresses Gallica, sociétés savantes qui sont des associations).

## 3. Sources

- Aucune décision de convention : déplacement dans les notes, ou délimiteur stable et taxinomie
  (voir la réflexion du 6 novembre, § 5.4 et § 10 question 4).
- La table `sources` de l'export garde le texte brut ; la décomposition (`source_parent`, pistes
  `nature = source`) est décrite dans `core/doc/exports_design.md` § 9.

## 4. Onglet Organisations de la webapp (finitions)

- Liste en échec non relancée, pagination figée ; page hors bornes qui affiche « Aucune
  organisation » avec un total non nul.
- Chargements en cours et affichage d'une session précédente non annulés au changement de session.
- « Reste à classer » non plafonné et ouvert d'office sur un filtre vide.
- Tests statiques par présence de chaînes seulement (pas d'invariant entre `OrganizationType` et
  les libellés).
- Défilement de la carte Stats déclenché trop tôt ; titre filtré lors d'un lien profond.
- Pas de test « Reste à classer » après modification d'un événement.
- Balayage quadratique des expériences proches si des milliers d'événements sont simultanés.
- `unmatched_total` et `unmatched_groups` de `CandidateIndex` jamais lus.
- Tests API : filtre `named_from`, `has_next` et ensemble vide non testés ; une chaîne passée comme
  `organization_ids` serait découpée en caractères ; le test de jeton accepte 401, 403 ou 422.
- Deux fonctions `_fold` différentes (repli ASCII et suppression des diacritiques) à unifier.

## 5. Atelier v1 (lieux)

- Pile d'annulation et conflits en attente perdus au redémarrage (l'écran le signale).
- Modification du `.gw` vérifiée à l'ouverture du projet seulement.
- Historique de navigation côté navigateur uniquement ; fichier choisi perdu quand l'écran
  Référentiel se redessine ; pas de tests JavaScript.
- Envoi de plus de 50 Mo écrit sur disque avant le refus ; course entre la vérification du port et
  le lancement.
- Bootstrap et Tabulator livrés (environ 780 Ko) mais inutilisés.
- Chaque vue reconstruit tout : performances à surveiller vers 20 000 écritures.
- Fenêtre entre le calcul de l'empreinte du `.gw` et sa lecture.
- Import qui échoue après 5 tentatives : erreur 500 en anglais (il faut une seconde instance qui
  modifie le référentiel en même temps) ; à transformer en 409 en français.
- Scinder des écritures déjà validées hors de leur lieu donne un groupe qui pointe encore vers ce
  lieu.
- Données de référence : codes INSEE et postaux non
  complétés par des zéros ; détection du séparateur fragile sur des en-têtes entre guillemets ;
  environ 90 codes postaux des collectivités d'outre-mer écartés.
- Une nouvelle écriture rattachée à un lieu existant ne propose pas ses niveaux écrits manquants.
- L'ancrage par nom peut réunir des lieux étrangers que la partition par codes avait séparés.
- Modifier les coordonnées, les dates ou la nature d'un niveau INSEE garde l'origine « insee » :
  l'origine est retrouvée par nom, type et identifiant.
- Registre v1 migré : une copie de sauvegarde est écrite à chaque tentative, même échouée.
- Un niveau sans type écrit après la commune l'emporte encore par la longueur de la chaîne : une
  faute de frappe (`Lille, Nrod`) est proposée pour toutes les écritures `Lille` du groupe.
- Migration : une variante proche d'un niveau seulement proposé (`Lome` à côté de `Lomme`) est
  encore proposée ; seuls les niveaux validés servent à la comparaison.
- `Lomme, Lille` donne deux fois Lille dans la chaîne (commune, puis niveau sans type).
- Le message « Rang … au niveau … » mêle le rang (compté depuis 0) et le numéro de niveau
  (compté depuis 1).
- Région écrite non comparée à la commune ; confiance plafonnée à « moyenne » après fusion par
  similarité ; horodatages non exportés ; suppression concurrente qui lève une `IntegrityError`.
- Publication : le job de test ne tourne que sous Python 3.12 ; l'ordre des étiquettes
  (`core-v*` avant `atelier-v*`) est documenté, pas imposé.
- Arrondissements : la correspondance entre anciens et nouveaux arrondissements n'est pas livrée,
  car elle n'est jamais univoque à l'échelle d'un arrondissement entier.
- Arrondissements : si les couches ALPAGE ne répondent plus, la table sort sans rues ni quartiers
  d'avant 1860 (repli prévu, non utilisé à ce jour).
- Rues disparues sans date d'arrêt : toutes rattachées à la période d'après 1860.
- La couverture mypy de `atelier/tools` est absente de la CI.
- « Paris 7 » (sans ordinal) ne résout aucune commune.
- Un « Q. » isolé est lu comme « quai ».
- Dates ouvertes (`<`, `>`) proches de 1860 : laissées « appliquée ».
- Marseille 1946 (création des arrondissements actuels) traité à l'année près.
- Un import dont le seul effet est de garder des précisions locales n'écrit pas d'entrée de
  journal.
- Rue disparue listée dans un « 5e ancien » : rattachée au 5e arrondissement actuel (période après
  1860) ; à vérifier sur des données réelles.

### DicoTopo (étape 3)

- L'API DicoTopo n'a pas été vérifiée en conditions réelles (réponses, limites de débit).
- Couverture : environ 52 départements ; les autres n'ont pas de propositions DicoTopo.
- Le type « commune » des articles n'est pas vérifié sur des données réelles.
- Un téléchargement en cours peut réindexer un département qui vient d'être retiré.
- La colonne Département est vide pour les départements non téléchargés.
- L'acceptation fait confiance au niveau envoyé par le client : seuls l'origine et l'identifiant sont
  vérifiés.

### GeoNames (étape 4)

- Les types `ADM1` / `ADM2` de GeoNames sont à compléter pays par pays (libellé et type de niveau).
- Le fichier `cities500` n'est pas utilisé.
- Les tâches GeoNames déjà en file ne sont pas annulées quand un pays repasse en « Garder tel qu'écrit ».
- Les pays historiques absents de la liste de l'INSEE n'apparaissent pas sur l'écran Pays : ils restent tels
  qu'écrits.
- Les limites de l'API (10 000 requêtes par jour, 1 000 par heure) viennent de la documentation de GeoNames ;
  elles n'ont pas été éprouvées en conditions réelles.

## 6. Moteur `core`

- Le parser retire les guillemets d'un lieu `#bp` mais pas d'un lieu `#mp` ni `#p` (audit de
  fidélité).
- Limites possibles, non vérifiées : `+date #dp lieu` sur une ligne `fam` lu comme mariage ; lieu
  entièrement numérique (`#bp 59512`) perdu sur une ligne d'enfant.
- mypy lancé avec la configuration de `core/pyproject.toml` : 28 erreurs (la CI ne l'utilise pas).
- `test_parse_command_summary` dépend de la largeur du terminal (passe avec `COLUMNS=300`).
- `core/doc/parser_fidelity_audit.md` et `parser_finalisation_design.md` citent encore
  `smoke_real_base.py`, supprimé.
- Exclusions ruff E203 et B008 redondantes, recopiées dans l'atelier.
