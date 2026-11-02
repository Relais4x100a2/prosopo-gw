# Finalisation du parser `.gw` : document de conception

Date : 1er novembre 2026, validé le 2 novembre 2026 (section 9).

Ce document fait suite à l'audit `parser_fidelity_audit.md`, qui dit **ce qui est cassé et pourquoi**. Il dit
**ce que l'on construit, dans quel ordre et comment on saura que c'est fini**. Il s'adresse à un développeur
qui prendra le chantier sans pouvoir interroger l'auteur ; les décisions prises avec le responsable du dépôt
sont marquées *(décision du responsable)*, celles de l'auteur *(choix de l'auteur)*, et ce qui reste ouvert
est dans la section 9.

## 1. Intention

`geneweb-py` doit lire un fichier `.gw` **exactement comme GeneWeb le lit**. La cible concrète est l'usage
d'un chercheur en prosopographie : il exporte un arbre massif depuis Geneanet, l'ouvre dans l'application
TOLDOT et doit y retrouver ce qu'il voit en ligne. Aujourd'hui les tests unitaires sont verts mais la première
utilisation réelle a déçu : conjoints et enfants absents, familles sans enfants, plantage à la recherche d'une
personne. L'écart entre « tests verts » et « ça marche sur ma base » est le problème à résoudre, pas seulement
une liste de champs.

Le principe directeur, validé par le responsable : **même comportement que le logiciel source GeneWeb, vérifié
contre GeneWeb**. Quand une règle est ambiguë, on lit `gwcomp.ml` et `db1link.ml` (compilateur `gwc`) et on
fait pareil. C'est la source de cohérence, donc de confiance.

## 2. Critère de fin *(décision du responsable)*

Le chantier est terminé quand les trois couches ci-dessous sont vertes, dans cet ordre.

1. **Tests** : la suite `core` passe, couverture ≥ 80 %, mypy à 0 erreur, ruff propre. Comme aujourd'hui.
2. **Mesure automatique sur bases réelles** : sur chaque base de recette, l'oracle GeneWeb (aller-retour
   `gwc` → `gwu`, section 6) donne **≥ 99 % de concordance** sur les cinq informations clés (section 3), et le
   parcours automatique de l'application (section 7.4) ne remonte aucun plantage.
3. **Recette humaine** : revue de débogage par Cursor, puis vérification manuelle par le responsable dans
   l'application sur **trois fichiers `.gw` réels exportés de Geneanet**, en comparant aux fiches en ligne.
   Le chercheur doit retrouver plus de 95 % des informations, idéalement 99 %.

Les trois bases de recette : le grand arbre actuel du responsable (≈ 4,8 Mo, 2 875 familles, ≈ 8 300
personnes), plus deux arbres plus petits qu'il fabriquera en important dans Geneanet un export Filae,
MyHeritage ou Geni, puis en exportant le `.gw`. Toutes ces bases restent hors dépôt, en lecture seule.

Précision sur la dépendance aux bases *(choix de l'auteur)* : les couches 1 et 2 et toute la partie
automatique du plan (phases 0 à 3.2) se font et se jugent sur le **grand arbre seul**, qui est disponible dès
maintenant ; les deux petits arbres y sont ajoutés dès qu'ils existent et doivent eux aussi atteindre les
99 %. Seule la recette humaine finale (couche 3) exige les trois fichiers, et c'est le responsable qui la fait.
Le builder n'est donc jamais bloqué par leur absence.

**La revue Cursor** est une revue de débogage que le responsable lance lui-même avec l'assistant de l'IDE
Cursor sur les commits de la phase. Elle passe quand chaque constat qu'elle remonte a été soit corrigé, soit
écarté par écrit dans le compte rendu de phase. Le builder ne la lance pas ; il livre un état revu et
reprend les constats.

## 3. Les cinq informations clés *(décision du responsable)*

Ce sur quoi un chercheur juge l'outil, et dont la perte le ferait abandonner : **dates, lieux, professions,
sources, témoins des événements**. Le plan priorise ces cinq champs partout où ils apparaissent :

- sur la ligne `fam` (conjoints, mariage) et dans le bloc `fevt` ;
- sur les lignes enfant `- h/f …` et les lignes témoin `wit …` ;
- dans les blocs `pevt` (naissance, baptême, décès, inhumation, événements personnalisés) ;
- dans les blocs `ind` quand il y en a.

Tout le reste (titres, alias, accès, notes en ligne `#bn`/`#dn`, `#mn`, `page-ext`, `wizard-note`) est
secondaire : lu correctement quand c'est sur le chemin, jamais prioritaire.

### Comment on compte

Une « information » est un champ non vide d'une personne, d'une famille ou d'un événement tel que `gwu`
le réécrit après `gwc`. Le taux de concordance est : informations identiques entre notre lecture et `gwu`,
divisées par les informations présentes chez `gwu`, pour les cinq familles de champs ci-dessus. On compte
séparément par champ (date de naissance, lieu de décès, source d'événement…) et on publie le tableau, jamais
une moyenne seule. Le comparateur ne sort que des comptages agrégés : aucun nom, lieu ou date réel.

## 4. Objectifs, non-objectifs, anti-objectifs

**Objectifs**

- Lire les cinq informations clés comme `gwc` sur tout le fichier, pas seulement la ligne `fam`.
- Appliquer les règles de réconciliation de `gwc` entre lignes et blocs d'événements (section 5.3).
- Exposer ces informations dans `to_dict`, les exports, l'API et l'application dès la fin de la phase 1.
- Rendre la mesure reproductible par n'importe qui : outillage d'oracle versionné, bases en argument.
- Retirer la cause racine des régressions : la reconstruction de champs à partir des jetons du lexer.

**Non-objectifs**

- Réécrire le lexer ou `syntax.py` : trop de surface partagée pour le même gain (audit § 3.4).
- Égaler GeneWeb sur ce qu'il ne lit pas lui-même (`wnote`, `comm` répétés) : on continue de les lire.
- Produire un `.gw` identique en sortie (writer) : hors périmètre.
- Comparer 100 % des fiches avec Geneanet en ligne : l'oracle local fait ce travail.
- Borne Python 3.8, publication PyPI, push des commits : décisions séparées du responsable.

**Anti-objectifs** (ce qui rendrait le chantier raté même si les tests passent)

- Une donnée réelle qui entre dans le dépôt, dans un test, un message de commit ou un document.
- Un champ qui « marche » sur fixtures mais pas sur base réelle, parce qu'on a corrigé un cas et pas la cause.
- Une règle qui s'écarte de GeneWeb sans l'avoir écrite et justifiée ici.
- Un comportement différent entre mode complet et streaming.

## 5. Décisions de conception

### 5.1 Dialecte cible : ce que Geneanet exporte *(choix de l'auteur, découle du critère de fin)*

Geneanet affiche et exporte à travers GeneWeb. L'oracle `gwc`/`gwu` est donc la même vérité que la fiche
en ligne. Quand Geneanet écrit quelque chose que `gwc` 7.1 refuse ou ignore (`wnote`, `comm` répétés),
on le lit quand même, et on le signale dans la doc du format. Le filtre de l'oracle retire ces lignes avant
`gwc`, comme aujourd'hui.

### 5.2 Lecture en mots bruts, généralisée *(déjà engagée par l'audit, confirmée)*

Un `.gw` est un format à mots séparés par des espaces. `gwc` lit chaque mot puis le décode (`copy_decode` :
`_` → espace, `\x` → `x`, puis `cut_space`). Le pilote `parser/words.py` fait pareil pour la partie mariage
de la ligne `fam`. On l'étend dans cet ordre : lignes enfant et témoin, puis infos des conjoints sur la
ligne `fam`, puis lignes `rel` et le reste, puis suppression des recolleurs (`mot_end`, `nom_end`, `nom_text`,
`place_run_end`, `texte_libre`, `_join_tokens_text`).

Le nouveau lecteur `read_person_infos` suit l'ordre de `set_infos` (`gwcomp.ml`, l. 878 en 7.1.0-beta2) :
alias de prénom et de nom, nom public, image, qualificatifs, alias, titres, accès, `#occu`, `#src`, naissance,
`#bp`, `#bn`, `#bs`, baptême, `#pp`, `#pn`, `#ps`, décès, `#dp`, `#dn`, `#ds`, inhumation, `#rp`, `#rn`,
`#rs`. **Tolérance conservée** : on accepte les marqueurs dans n'importe quel ordre, parce que les tests
existants le font et qu'une tolérance partielle perd des données sans prévenir. Même logique pour le
qualificatif placé avant le `+` (audit § 3.2) : on complète la tolérance, on ne la retire pas.

Les lecteurs restent des fonctions pures dans `words.py`, qui renvoient des dataclasses, et sont branchés dans
`gw_parser.py` via `_line_words`. Le texte source est toujours disponible (`_source`, y compris en streaming).

### 5.3 Réconciliation lignes / blocs d'événements : la règle de `gwc` *(décision du responsable)*

Vérifié dans `bin/gwc/db1link.ml` (7.1) : `update_family_with_fevents`, `update_fevents_with_family`,
`update_person_with_pevents`, `update_pevents_with_person`.

**Familles.** Si la famille a un bloc `fevt`, le bloc fait foi : GeneWeb parcourt les événements et recopie
dans les champs de la famille la date, le lieu, la source, la note et les témoins du **dernier** événement de
type mariage (`#marr`, et à défaut `#enga`, `#marc`, `#marb`, `#marl`, `#noment`, `#nmar`, `#anul`, `#pacs`),
et le **dernier** divorce ou séparation. Un contrat de mariage (`#marc`) donne une date « vers » et pas de
lieu. Le type d'union est déduit de l'événement retenu. Si la famille n'a **pas** de bloc `fevt`, GeneWeb
fabrique les événements à partir de la ligne `fam` : un événement mariage (ou du type correspondant au
qualificatif) avec la date, le lieu, la source et les témoins de la ligne, et un événement divorce ou
séparation s'il y a lieu.

**Personnes.** Même principe avec `pevt` : si le bloc existe, le **premier** événement de naissance,
baptême, décès, inhumation ou crémation remplace les champs correspondants de la personne (date, lieu, note,
première source). Un décès sans date garde l'état « mort, date inconnue » ou les marqueurs `#od`/`#mj`
existants. Sans bloc, les événements sont fabriqués depuis les champs de la personne.

**Chez nous** : la règle s'applique **à la fin du parse**, dans une passe dédiée, après résolution des
références croisées. `Family.events` et `Person.events` deviennent la source de vérité pour l'onglet
événements ; `marriage_*`, `birth_*`, etc. deviennent des champs dérivés mais toujours remplis, pour que les
consommateurs existants ne changent pas. Un drapeau `metadata["events_synthesized"] = True` marque les
événements fabriqués. L'oracle vérifie les deux vues puisque `gwu` les réécrit toutes deux.

**Pourquoi « le dernier mariage » est bien ce que Geneanet affiche.** La fiche Geneanet est rendue par
GeneWeb à partir de la base compilée par `gwc`, donc ses champs scalaires (date, lieu du mariage) sont
exactement ceux que la règle ci-dessus produit, et sa liste d'événements est la liste complète. En suivant
`gwc`, on affiche la même chose par construction. Le comparateur de la section 3 mesure **les deux** : les
champs scalaires de la personne et de la famille, et la liste des événements (type, date, lieu, source,
témoins).

**Identifiants** *(choix de l'auteur)* : les événements synthétisés sont **ajoutés en fin de liste**, donc
les indices des événements déjà lus ne bougent pas. Aucune migration n'est prévue : l'identifiant
d'événement de l'API (`stable_event_id`, `api/serialization.py`) inclut aujourd'hui `id(event)` et n'est
donc pas stable d'une exécution à l'autre, et le fichier compagnon `*.org.json` ne repose sur aucune
promesse de stabilité qu'on casserait. Les personnes anonymes reçoivent des identifiants `?_?_N` qui
n'existaient pas, donc aucun lien existant ne change de cible. Rendre `stable_event_id` réellement stable
(sans `id(event)`) est une amélioration souhaitable mais hors périmètre de ce chantier.

### 5.4 Conjoint `? ?` : une personne anonyme *(décision du responsable)*

La relation elle-même est une information : on sait que la personne a eu un conjoint. On fait comme `gwc`
(`insert_undefined`, `db1link.ml` l. 273) : un `?` en prénom ou en nom n'est jamais cherché dans l'index, donc
**chaque occurrence crée une personne distincte**.

Modèle : `Person.is_anonymous: bool = False`, mis à `True` pour ces personnes. Identifiant : la formule
actuelle `{last_name}_{first_name}_{occurrence_number}` donnerait `?_?_0` pour toutes ; on conserve
`last_name = "?"`, `first_name = "?"` et on attribue un `occurrence_number` **unique par généalogie** via un
compteur du parser, ce qui donne `?_?_0`, `?_?_1`, … sans collision avec aucune personne nommée. `display_name`
renvoie `"?"` tel quel ; l'affichage « Inconnu » est du ressort des consommateurs, qui testent
`is_anonymous`. `Family.spouses_unknown` reste rempli (il dit que la ligne déclarait des inconnus) et
`husband_id`/`wife_id` pointent désormais vers les personnes anonymes. `to_dict` expose `is_anonymous`.

Point d'attention pour le builder : les 47 familles « sans épouse légitime » et 42 « sans mari » de l'audit
changent de statut ; les tests `test_unknown_name_placeholders.py` doivent être réécrits en conséquence, et
les statistiques de l'application (nombre de personnes) doivent exclure ou distinguer les anonymes.

### 5.5 Décodage de `_` et `\_` : comme `gwc`, partout *(décision du responsable, option B retenue § 9.1)*

Aujourd'hui les lieux sont stockés bruts (`Ville_A`), certaines sources décodées par `replace("_", " ")` qui
ignore l'échappement (`X\_Y` → `X\ Y`), et `burial_place` décodé alors que les autres lieux ne le sont pas.
Décision : **tous les champs texte sont décodés par `decode_word`**, lieux compris, sources comprises
(`marriage_source`, `person_source` inclus). C'est ce que `gwc` fait, donc ce que Geneanet affiche.

Contrainte posée par le responsable : `place.py` découpe `[complément]_-_lieu` sur `_-_` ; le décodage ne
doit pas casser ce découpage. Deux modalités ont été étudiées ; la **B** est retenue (§ 9.1) :

- **A. Décoder à l'exposition** : le modèle garde le mot brut, `to_dict`, les exports, l'API et l'application
  décodent via `parse_place`/`decode_word`. Sûr pour `place.py`, mais tout consommateur qui lit l'attribut
  directement (c'est le cas de l'application : `event.place`) voit encore `_`.
- **B. Décoder au parse** : le modèle stocke le texte décodé ; `parse_place` accepte déjà le séparateur
  ` - ` (regex `\s+-\s+`) et son `_humanize` est remplacé par `decode_word` pour les entrées encore brutes.
  Un seul endroit, cohérent avec `gwc` ; mais `ParsedPlace.raw` ne contient plus le mot `.gw` d'origine et
  l'export GEDCOM/JSON/XML écrit du texte décodé.

Dans les deux cas, le premier commit est indépendant et sans risque : remplacer les 20 `replace("_", " ")`
de `gw_parser.py` par `decode_word`.

### 5.6 `to_dict` et consommateurs en phase 1, pas en phase 3 *(décision du responsable)*

`Person.to_dict` doit écrire `person_source`, `birth_source`, `death_source`, `baptism_*`, `burial_*`,
`is_anonymous` ; `Family.to_dict` doit écrire `marriage_source`, `family_qualifiers`, `common_birth_place`,
`common_children_source`, `spouses_unknown`, et les témoins et événements déjà présents. Les modèles
Pydantic de l'API (`api/models/`) et les exports (`formats/`) sont alignés dans la même phase. Les cinq
informations clés doivent être visibles de bout en bout à la fin de la phase 1.

### 5.7 Plantage de l'application : trace exacte d'abord *(décision du responsable)*

La phase 0 relance l'application sur le grand arbre et capture la trace complète de l'erreur observée sur
l'onglet événements à la recherche d'une personne, avant toute correction. Streamlit affiche déjà
`st.exception(e)` sur la page d'upload ; pour les autres pages, le builder ajoute le même garde-fou ou lit
les logs du conteneur. La trace est consignée (sans donnée nominative) dans le compte rendu de phase 0.

### 5.8 Outillage d'oracle versionné *(choix de l'auteur, prérequis de l'audit)*

Les scripts d'oracle vivent aujourd'hui dans un répertoire temporaire et se perdent. Ils entrent dans le
dépôt sous `core/tools/oracle/` :

- `Dockerfile` : compile GeneWeb depuis les sources officielles, dépôt `github.com/geneweb/geneweb`, tag
  **`v7.1.0-beta2`** (tag annoté `848b920a`, commit `2115f6af`), avec accès réseau au build. C'est **cette
  source qui fait foi** pour toute règle recopiée dans ce document et pour les numéros de ligne cités
  (`lib/gwcomp.ml`, `bin/gwc/db1link.ml`, `lib/gwuLib.ml`). Le fork local `geneweb-org` hors monorepo est une
  commodité de lecture, pas la référence : il contient du travail non figé et ses numéros de ligne diffèrent.
  GeneWeb 7.0 est exclu : il refuse les bases exportées de Geneanet ;
- `run.sh <base.gw> <dossier_sortie>` : filtre, `gwc`, `gwu` dans un conteneur jetable ; le dossier de sortie
  est obligatoire et hors dépôt par défaut ;
- `filter.py` : retire ce que `gwc` refuse (`wnote`, `comm` répétés) ; **ne retire plus** les blocs `fevt`,
  puisqu'on applique désormais la règle de `gwc` (section 5.3) ;
- `compare.py` : apparie familles et personnes entre notre `Genealogy` et la relecture du `.gw` produit par
  `gwu`, et sort le tableau de concordance par champ (section 3). Il remplace `oracle_cmp.py`,
  `oracle_psrc.py` et `oracle_child.py` ;
- `README.md` : mode d'emploi, et rappel qu'aucune sortie n'est à versionner.

Un `.gitignore` local exclut tout fichier de données et de résultat. L'oracle tourne en mode complet et en
streaming (le streaming s'active au-delà de 10 Mo ; le builder force les deux modes).

### 5.9 Vérification dans l'application *(choix de l'auteur)*

Un parcours automatique des pages Streamlit sur base réelle, lancé à la main, qui charge le fichier, traverse
chaque page et remonte les exceptions. `streamlit.testing.v1.AppTest` permet de le faire sans navigateur.
Emplacement : `app/docker/geneweb-app/tests/smoke_real_base.py`, chemin de la base par variable
d'environnement, sortie limitée aux comptages et aux traces. Non exécuté en CI (pas de base réelle).

### 5.10 Comparaison avec Geneanet : par échantillon, via le navigateur *(choix de l'auteur)*

L'auteur a accès au navigateur Chrome du responsable. Plutôt qu'un fichier d'identifiants, le responsable
ouvre une session Geneanet connectée dans Chrome ; l'auteur navigue sur les fiches avec cette session et ne
stocke rien. Échantillon de 30 à 50 personnes par base, choisi pour couvrir les cas difficiles (sources en
URL, professions avec parenthèses, conjoints anonymes, familles à `fevt` multiples, enfants sans sexe), plus
10 tirées au hasard. Pour chacune, les cinq informations clés sont comparées entre fiche en ligne et sortie du
parser. Aucune capture ni extrait nominatif n'entre dans le dépôt ; seul le décompte est consigné. Si un
fichier d'identifiants devait exister, il vivrait hors du dépôt et hors du contexte Docker.

Cadre : il s'agit de l'arbre du responsable, consulté avec sa session, à un rythme de lecture humaine
(quelques dizaines de fiches, sans balayage), à sa demande. Ce relevé est une **aide à la recette, pas un
critère de fin** : le critère reste la recette manuelle du responsable (section 2). Repli si le responsable
préfère ne pas ouvrir sa session ou si Geneanet s'y oppose : il fournit des captures d'écran des fiches de
l'échantillon, et la comparaison se fait sur ces captures.

### 5.11 Ce qui reste séparé *(hors périmètre, pour mémoire)*

Compatibilité Python 3.8 du paquet `core` (on continue de ne pas utiliser de syntaxe 3.10+ dans `core/src`),
publication PyPI, push des 26 commits locaux. Le chantier continue de commiter localement, un sujet par commit,
sans push.

## 6. L'oracle GeneWeb en bref

```
base.gw ──filter.py──▶ base_f.gw ──gwc──▶ base.gwb ──gwu──▶ rt.gw
                                                               │
geneweb-py ◀── parse(base.gw) ── compare.py ── parse(rt.gw) ◀──┘
```

`gwu` écrit les infos d'une personne qui a des parents sur sa **ligne enfant**, et les infos de mariage à la
fois sur la ligne `fam` et dans le bloc `fevt`. Le comparateur lit donc `rt.gw` avec notre propre parser
(après la phase 1 il lit les lignes enfant correctement) et compare objet à objet : c'est circulaire pour
les bugs de lecture partagés, mais `rt.gw` est écrit par `gwu` de façon canonique (un seul ordre, un seul
encodage), ce qui élimine la quasi-totalité des cas difficiles. Pour les champs où ce doute subsiste, le
comparateur garde une seconde lecture naïve de `rt.gw` par découpage sur les espaces, comme aujourd'hui.

## 7. Phases, livrables, critères de passage

Chaque phase se termine par : tests verts, oracle relancé sur les bases disponibles dans les deux modes, un
compte rendu agrégé ajouté à `parser_fidelity_audit.md` (section « Mesures »), et les commits locaux
correspondants. La revue Cursor intervient à la fin des phases 1 et 3 *(choix de l'auteur)*.

### Phase 0 : voir où on en est, rendre la mesure reproductible

1. Reconstruire l'image Docker (`core/` a changé, l'image installe `geneweb-py` non éditable) et relancer
   l'application sur le grand arbre. Noter, onglet par onglet, ce qui manque encore ; capturer la trace exacte
   du plantage de l'onglet événements (§ 5.7). Vérifier au passage **quelles pages** le responsable a
   utilisées, car l'application du monorepo n'a aujourd'hui que des pages d'extraction et d'annotation de
   `pevt` (voir § 9.2).
2. Versionner `core/tools/oracle/` (§ 5.8), reconstruire l'image GeneWeb 7.1, rejouer la mesure de l'audit
   et vérifier qu'on retrouve ses chiffres (0 écart sur la ligne `fam`).
3. Étendre `compare.py` aux personnes et aux événements, et publier le **tableau de référence** des cinq
   informations clés avant toute correction. C'est la ligne de base du chantier.

Passage : trace du plantage consignée, oracle rejouable par une commande, tableau de référence publié.

### Phase 1 : les cinq informations clés, de bout en bout

Un commit par sujet, dans cet ordre, chacun validé par l'oracle.

1. `replace("_", " ")` → `decode_word` dans `gw_parser.py` (corrige `\_`, 47 sources de l'audit).
2. `read_person_infos` dans `words.py`, branché sur les lignes enfant (`_parse_child`) puis témoin. Effets
   attendus sur le grand arbre : 405 `#src` retrouvés, 30 professions entières, 24 fausses dates de
   naissance disparues, `csrc`/`cbp` appliqués seulement en l'absence de valeur propre. Retirer la note
   `Source: …` après avoir vérifié qui la lit.
3. Qualificatif et code de sexe avant le `+` (audit § 3.2) : compléter la tolérance dans `syntax.py` et
   `_parse_family_line`.
4. Décodage des lieux au parse (option B, § 9.1) ; adaptation de `place.py` et tests des toponymes à tiret.
5. Conjoint `? ?` → personne anonyme (§ 5.4), réécriture des tests concernés.
6. Réconciliation `fevt`/`fam` et `pevt`/`ind` selon la règle de `gwc` (§ 5.3), passe de fin de parse, et
   retrait du filtre `fevt` dans l'oracle. Synthèse des événements manquants.
7. `to_dict`, modèles Pydantic de l'API, exports GEDCOM/JSON/XML (§ 5.6). Un test par format qui vérifie la
   présence des cinq informations clés sur une fixture synthétique complète.
8. Reconstruction de l'image, relance de l'application, nouvelle mesure, revue Cursor.

Passage : ≥ 99 % de concordance par champ sur le grand arbre pour les cinq informations clés, dans les deux
modes ; plus aucune des trois observations initiales (conjoint ou enfants absents, familles sans enfants,
plantage) reproductible.

### Phase 2 : finir la lecture en mots bruts

1. Infos des conjoints sur la ligne `fam` par `read_person_infos` (elles passent encore par `syntax.py`).
2. Lignes `rel`, `ind` et toute ligne restante lue par jetons.
3. Suppression des recolleurs et du code mort (≈ 1 100 lignes), couverture maintenue.
4. Champs lus mais non stockés quand ils sont sur le chemin : `#mn` → `Family.marriage_note`, notes en ligne
   `#bn`/`#pn`/`#dn`/`#rn` → `Person.*_note`.

Passage : oracle inchangé ou meilleur, aucun recolleur restant, tests de parité complet/streaming verts.

### Phase 3 : de bout en bout et recette

1. Parcours automatique de l'application (§ 5.9) sur chaque base disponible ; correction des plantages.
2. Comparaison par échantillon avec Geneanet (§ 5.10) sur chaque base ; chaque écart devient soit un correctif,
   soit une ligne documentée dans « différences de modèle » de l'audit.
3. Mise à jour de `core/doc/geneweb/gw_format_documentation.md` : règles de `gwc` adoptées, dialecte Geneanet.
4. Revue Cursor, puis recette manuelle du responsable sur les trois fichiers.

Passage : critère de fin de la section 2 atteint.

## 8. Ce qui est laissé au builder

- Le découpage exact des dataclasses de `words.py` et la signature de `read_person_infos`, tant que le lecteur
  reste pur et testé seul (`test_words.py`).
- L'emplacement de la passe de réconciliation (fin de `GeneWebParser.parse` ou `MultiPassParser`), tant
  qu'elle tourne dans les deux modes et après résolution des références.
- Le format exact du tableau de concordance et la structure interne de `compare.py`.
- Le choix entre `AppTest` et un autre pilotage pour le parcours de l'application.
- L'ordre des commits à l'intérieur d'une étape, et les fixtures synthétiques à créer (une par cas difficile
  observé sur base réelle, toujours avec des noms fictifs du type `DUPONT Jean`).
- Les ajustements de `Dockerfile.dockerignore` strictement nécessaires, sans élargir la liste d'autorisation.

## 9. Questions tranchées et point restant

Document validé par le responsable le 2 novembre 2026.

### 9.1 Modalité du décodage des lieux : **option B, au parse** *(décision du responsable)*

Le modèle stocke le texte décodé par `decode_word`, comme `gwc`, pour ne pas propager de `_` dans les
consommateurs (`event.place`, exports, Streamlit). `parse_place` détecte le séparateur hiérarchique sur
` - ` (tiret entouré d'espaces) et son `_humanize` est remplacé par `decode_word` pour les entrées encore
brutes. **Exigence de test** : un toponyme à tiret simple sans espaces (`Saint-Maur-des-Fossés`,
`Saint-Denis`) ne doit être ni découpé ni altéré ; un lieu `[Atelier Rose] - Lyon` décodé doit donner le
complément `Atelier Rose` et le nom `Lyon` ; les deux cas sont joués en mode complet et en streaming.

### 9.2 Interface à trois onglets : emplacement à préciser par le responsable

Le responsable confirme que l'interface testée a trois onglets (Personne / Famille / Événements), mais son
chemin n'a pas été transmis. Recherche faite le 2 novembre 2026, sans résultat : elle n'est ni dans
`app/docker/geneweb-app/pages/` (pages `pevt` uniquement), ni dans les archives `geneweb_revamped` et
`Geneweb` V2 (Flask à une seule route, parser regex propre), ni sur une branche locale (toutes fusionnées
dans `main`). **Tant que le chemin manque**, la phase 0 capture la trace sur ce qui existe : les pages
Streamlit actuelles et l'API REST (`/api/v1/events`, recherche par personne) sur le grand arbre ; le parcours
automatique de la phase 3 vise les mêmes cibles. Dès que le responsable indique le fichier, ou dit que ces
écrans sont à construire, le document est mis à jour et les deux phases ajustées.

## 10. Repères

- Audit et mesures : `core/doc/parser_fidelity_audit.md`.
- Référence OCaml : `gwcomp.ml` (lecture), `bin/gwc/db1link.ml` (réconciliation, personnes anonymes),
  `lib/gwuLib.ml` (écriture), GeneWeb 7.1.0-beta2 ou fork `geneweb-org` hors monorepo.
- Spécification du format : `core/doc/geneweb/gw_format_documentation.md`.
- Règles du dépôt : `AGENTS.md` racine et `core/AGENTS.md` (dépôt public, fixtures synthétiques, `uv`,
  mypy strict, couverture ≥ 80 %, un sujet par commit, pas de push sans accord).
