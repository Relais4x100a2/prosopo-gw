# Audit de fidélité du parser `.gw` : bilan au 1er novembre 2026

Ce document s'adresse à un développeur qui rejoint le chantier. Il dit ce qui a été corrigé dans le parser
de `geneweb-py`, comment, ce qui reste ouvert et par où reprendre. Il suppose une connaissance de Python,
mais pas du format GeneWeb ni de l'historique du code.

## En bref

- **But du chantier** : que `geneweb-py` lise un fichier `.gw` comme le lit GeneWeb officiel (compilateur `gwc`).
- **Fait** : 26 commits (`b18ad95` → `30fd986`), tous locaux et non poussés. Sur une base réelle locale,
  la partie famille de la ligne `fam` est maintenant identique à ce que produit GeneWeb 7.1 pour les
  2 875 familles. Les seuls écarts restants sont des différences de modèle, expliquées.
- **Prochain chantier** : les infos en ligne des enfants et des témoins (`_parse_inline_personal_info`).
  Sur la même base, on mesure 405 sources `#src` perdues, 30 professions coupées (dont 24 qui inventent
  une date de naissance) et 47 sources mal décodées.
- **Direction d'architecture** : lire la ligne brute mot à mot, comme `gwc`, au lieu de recoller les jetons
  du lexer. Un pilote (`parser/words.py`) couvre la partie mariage de la ligne `fam` et l'oracle GeneWeb
  l'a validé.
- **Prérequis pour reprendre** : l'outillage de comparaison avec GeneWeb n'est pas versionné (§ 4.1).

## 1. Ce qu'il faut savoir avant de commencer

### 1.1 Le format et sa référence

Un `.gw` est un format **à mots** : chaque champ est un mot séparé par des espaces, une espace dans une
valeur s'écrit `_`, et `\_` est un `_` littéral (fréquent dans les URL). La spécification du dépôt est
`core/doc/geneweb/gw_format_documentation.md`. En cas de doute, la référence est le code du compilateur,
`gwcomp.ml` (GeneWeb 7.1, ou le fork `geneweb-org` hors monorepo). `gwc` décode chaque mot par
`copy_decode` (`_` → espace, `\x` → `x`) puis `cut_space` (retire une espace en tête et en fin).

Fonctions de `gwcomp.ml` utiles (numéros de ligne de la 7.1.0-beta2, indicatifs) :

| Fonction | Ligne | Rôle |
|---|---|---|
| `get_field` | 148 | lit `#tag mot` et renvoie le mot |
| `get_occu`, `get_sources` | 509, 513 | `#occu mot`, `#src mot` : un seul mot chacun |
| `get_mar_date` | 796 | partie mariage de la ligne `fam` |
| `set_infos` | 878 | infos d'une personne, **dans un ordre fixe** (voir ci-dessous) |
| `parse_parent` | 973 | conjoint sur la ligne `fam` |
| `parse_child` | 997 | ligne enfant `- h Prénom[.N] [NOM] …` |

Ordre de `set_infos` : alias de prénom et de nom, nom public, image, qualificatifs, alias, titres, accès
(`#apubl`/`#apriv`), `#occu`, `#src`, date de naissance, `#bp`, `#bn`, `#bs`, baptême, `#pp`, `#pn`, `#ps`,
date de décès, `#dp`, `#dn`, `#ds`, inhumation, `#rp`, `#rn`, `#rs`. Pour un enfant, `#src` et le lieu de
naissance ne prennent les valeurs communes de la famille (`csrc`, `cbp`) **que si l'enfant n'a pas les
siennes**.

Grammaire de la partie mariage (`get_mar_date`), dans l'ordre :

1. `+[date]` ;
2. relation éventuelle : `#nm` ou `#eng` sans code ; `#noment` avec un code facultatif ; `#nsck`, `#nsckm`,
   `#banns`, `#contract`, `#license`, `#pacs`, `#residence` suivis d'un code de sexe de deux lettres
   (`mf`, `fm`, `mm`, `ff`, `m?`…) ;
3. `#mp`, `#mn`, `#ms`, un mot chacun ;
4. `-[date]` (divorce) ou `#sep` ;
5. l'épouse.

### 1.2 Le pipeline et la cause racine des bugs

```
.gw → lexical.py (jetons) → syntax.py (SyntaxNode) → gw_parser.py (+ multipass_parser.py) → Genealogy
```

Le lexer découpe les mots qui contiennent `/ : ( ) " -` ou des chiffres : par exemple, `3_E_041/472`
donne plusieurs jetons. Les couches suivantes doivent recoller ces morceaux, et chaque bug corrigé a
ajouté son propre recolleur (`mot_end`, `nom_end`, `nom_text`, `place_run_end` dans `place_tokens.py`,
`texte_libre`, `_join_tokens_text`). Une quinzaine des 26 commits corrigent ce même défaut sur des champs
différents. D'où la décision de lire la ligne brute (§ 2.7 et § 3.4).

Le texte source est disponible pour cette lecture :

- `GeneWebParser._source` contient le texte complet, en mode complet comme en streaming (le streaming
  s'active au-delà de 10 Mo, y compris dans l'application) ;
- il ne vaut `None` que si l'on appelle `MultiPassParser` sans contenu, cas où `_line_words` recolle les
  jetons contigus en repli.

### 1.3 Méthode de vérification

- **Tests** : fixtures synthétiques uniquement, un fichier de test par sujet. Chaque nouveau test échoue
  sans son correctif, et les cas sensibles sont joués en mode complet et en streaming.
- **Base réelle** : une base locale, hors dépôt, en lecture seule (≈ 4,8 Mo, 2 875 familles,
  ≈ 8 300 personnes). On n'en recopie rien : seuls des comptages agrégés sortent des scripts.
- **Première référence, le texte brut** : des scripts qui découpent les lignes sur les espaces. C'était
  suffisant tant que le parser recollait des jetons, mais cela tourne en rond dès que le parser lit lui
  aussi des mots.
- **Seconde référence, l'oracle GeneWeb** : un aller-retour `gwc` → `gwu` avec GeneWeb 7.1.0-beta2,
  compilé depuis les sources et exécuté dans un conteneur jetable. GeneWeb 7.0.0 refuse cette base (lignes
  `wnote` et `comm` répétées).
  - Avant `gwc`, un filtre retire 72 lignes `wnote` (aucun GeneWeb officiel ne les lit), 30 `comm`
    répétés et 2 685 blocs `fevt`. Chez GeneWeb, un bloc `fevt` remplace les données de mariage de la
    ligne `fam`, donc la comparaison porte sur la ligne `fam` seule.
  - Le comparateur apparie les familles une à une et compare : date, type d'union, sexes, `#mp`, `#ms`,
    divorce, séparation, source de famille. Un second comparateur vérifie les `#src` des conjoints.
  - Limite : `gwu` écrit les infos d'une personne qui a des parents sur sa **ligne enfant**. Ces personnes
    (1 453 maris, 1 268 épouses) ne sont pas encore comparées.

## 2. Points traités

État vérifié au 1er novembre 2026 :

- 1 676 tests passent (17 ignorés) ;
- couverture 89 % (`gw_parser.py` 80 %, `syntax.py` 92 %, `words.py` 99 %) ;
- ruff et ruff format propres, mypy à 0 erreur.

Les comptages « avant → après » portent sur la base réelle.

### 2.1 Ligne `fam` : conjoints perdus ou faux (12 commits)

Point de départ : 1 079 familles sans épouse, dont une quarantaine seulement étaient légitimes, et
44 épouses fictives (identifiants `mf_NOM_0`).

| Commit | Problème | Résolution |
|---|---|---|
| `b18ad95` | Avec `#bp`/`#dp Ville,_Région,_Pays`, seul le premier jeton était gardé et la suite devenait le nom de l'épouse. | Lecture par `_parse_short_place`, comme `#pp`. |
| `3a6aa58` | `???` était lu comme une date, et le conjoint disparaissait. | Lu comme un nom. Seul `?` exact signifie « inconnu, pas de personne créée ». |
| `d68f5b4` | `od`/`mj` (et `#od`/`#mj`) après la naissance coupaient la ligne avant le `+`. | Reconnus dans les deux couches (`is_obviously_dead`, `is_young_death`). |
| `72ffb30` | Une source `#ms` en URL ou un `#mp` contenant `;` débordait sur le nom de l'épouse (≈ 845 familles). | Chaque valeur est lue comme un mot délimité par des espaces. |
| `cd1314a` | Le code de sexe (`mf`…) après `#noment`, `#banns`… était lu comme le nom de l'épouse (149 pertes, 44 épouses fictives). | Code consommé après le qualificatif, dans les deux couches. |
| `d9df5c7` | `#src` du mari avant le `+` coupait la ligne (≈ 190 familles). | `#src` suivi de son mot entier. |
| `150bbdc` | `#bs`/`#ds`/`#pp`/`#ps`/`#rp`/`#rs` étaient lus jusqu'au premier jeton ressemblant à une date ; un lieu `_[complément]_-_Ville` était coupé. | Un mot par champ ; marqueur de baptême `!` conservé ; `?` isolé = décès de date inconnue. |
| `4aa8805` | `#buri`/`#crem` inconnus de `syntax.py` (le reste de la ligne tombait) ; `#occu` s'arrêtait au premier chiffre. | Balises consommées ; profession lue comme un mot. |
| `02be0c9` | Un seul `?` dans le nom ou le prénom supprimait la personne. | Seul `? ?` désigne un conjoint absent, comme dans GeneWeb. |
| `0b6a3a5` | Noms composés coupés (`MARTIN*`, `A/_B`, `_(Dit)_MARTIN`, `Anne,_Autre`). | Un mot entier, arrêt avant `.N` et avant l'alias. |
| `f9084d9` | Alias collé `Anne"Dit"` ; `#mp 9th_Ave` pris pour une date. | L'alias fait partie du nom ; un `#mp` est toujours un lieu. |
| `ee562fe` | Le tiret de `#occu Maire_(1850-1900)` était lu comme un divorce ; `#sep` écrasait `#nm`. | Profession lue comme un mot ; la séparation va dans `is_separated`. |

Résultat :

- familles sans épouse : 1 079 → 47, toutes légitimes (`+ ? ?`, `#noment mf ? ?`, `? ?.N`) ;
- aucune épouse fictive ;
- 42 familles sans mari, toutes `? ?` ;
- statuts comparés au texte brut sans écart : 2 752 mariages, 109 divorces (92 datés), 13 `#nm`, 1 `#sep` ;
- `#eng` est absent de la base et n'est couvert que par un test synthétique.

### 2.2 Témoins, événements libres, blocs `pevt` (3 commits)

| Commit | Problème | Résolution | Effet |
|---|---|---|---|
| `4850ba3` | Un nom de témoin avec guillemets ou `/` mettait fin au bloc ; un `#src` en URL était coupé. | Mêmes lecteurs de mots que la ligne `fam`. | 796 → 809 témoins sur 809 |
| `a1a074e` | Les balises d'événement avec accent, apostrophe ou guillemet étaient ignorées (regex ASCII). | Une balise est un mot délimité par des espaces. | événements de famille 3 039 → 3 051 sur 3 051 |
| `2bac244` | L'en-tête `pevt` lisait un jeton par nom et ignorait `.N` : événements attribués au mauvais homonyme, personnes fantômes. | Noms en mots entiers et `.N` respecté. | 6 353 blocs exacts, 64 personnes fantômes en moins |

### 2.3 Texte libre lu tel quel (3 commits)

| Commit | Problème | Résolution |
|---|---|---|
| `b18fbb7` | Blocs `notes` reconstruits à partir des jetons : retours à la ligne, guillemets et `<pre>` perdus. | Texte brut entre `beg` et `end notes`, plafond de taille conservé, `.N` respecté. |
| `e5d8466` | Lignes `note` de `pevt`/`fevt`, `comm`, `src` reconstruites ; les mots `wit`, `marr`, `birt` coupaient le texte. Une espace en fin de ligne produisait un jeton `UNKNOWN '\n'` qui masquait la note suivante. | Lecture dans la source ; le lexer émet un `NEWLINE`. Notes d'événement : 2 884 → 2 958 sur 2 958 ; `comm` 43/43 ; `src` 306/306. |
| `745b53a` | En-tête `gwplus` et `encoding:` jamais lus ; bloc `notes-db` aplati. | En-tête lu ; `notes-db` conservé tel quel. |

### 2.4 Enfants (2 commits)

| Commit | Problème | Résolution |
|---|---|---|
| `86e3c14` | `cbp`/`csrc` devenaient de faux commentaires et n'étaient jamais appliqués. | `Family.common_birth_place` et `common_children_source`, appliqués aux enfants sans valeur propre, y compris quand le bloc `beg` est détaché de la ligne `fam`. 0 écart. |
| `80a46d4` | Enfants lus « NOM Prénom » alors que le format est « Prénom[.N] [NOM] » ; prénoms composés tronqués. | Mots entiers et `.N` ; fixtures et tests mis à l'ordre du format. 4 264 enfants, sexes conformes. |

### 2.5 Blocs `fevt` et `pevt` (2 commits)

| Commit | Problème | Résolution |
|---|---|---|
| `4f9db4e` | `#marr`/`#div`/`#sep`/`#enga` reconstruits à partir de jetons dédiés : 1 776 lieux coupés, 731 sources perdues, 2 lieux pris pour la date. | Lecture de la ligne brute, comme les autres balises. 16 021 événements et 2 115 témoins d'événement, 0 écart. |
| `eff21ff` | Un `#birt`/`#deat` sans date dans `pevt` effaçait une date connue. | La date connue est conservée (2 personnes concernées). |

Les 14 954 dates d'événement ont été comparées sans écart : préfixes `~ ? < >`, intervalles, calendriers
républicain et hébreu, dates textuelles `0(…)`.

### 2.6 Streaming (1 commit)

`2ed92c3` : le lexer de streaming produit des positions globales et conserve le texte lu (`source_text`),
transmis comme `_source`. Avant, les lecteurs de ligne brute retombaient sur la reconstruction par jetons
dès qu'un fichier dépassait 10 Mo. Des tests de parité comparent les deux modes sur toutes les fixtures.

### 2.7 Lecture en mots bruts : le pilote (3 commits)

- **`7f5cd47`** : nouveau module pur `core/src/geneweb_py/core/parser/words.py`.
  - `split_words`, `word_spans`, `decode_word` (équivalent de `copy_decode`), `cut_space`, `is_sex_code`.
  - `read_marriage_part`, qui suit `get_mar_date` et renvoie un `MarriagePart` plus l'indice du premier
    mot de l'épouse.
  - Il est branché dans `_parse_family_line` via `_line_words`, qui aligne les mots bruts sur les jetons
    par leur position.
  - Tolérances historiques conservées : date détachée après `+`, `-`, `#sep` ou `#div` ; marqueurs dans
    n'importe quel ordre ; qualificatifs avant le `+`.
- **`2cef062`** : `FamilyQualifier.PACS` et `RESIDENCE`. Ces qualificatifs étaient lus puis jetés.
- **`30fd986`** : un `#src` de la ligne `fam` est la source du **conjoint**, pas de la famille : celle du
  mari s'il précède le `+`, celle de l'épouse s'il suit son nom. Il est stocké en mot brut dans
  `person_source`, et seule une ligne `src` donne `Family.family_source`.

Oracle GeneWeb 7.1, identique en mode complet et en streaming :

| Champ comparé | Avant le pilote | Après `30fd986` |
|---|---|---|
| source de mariage (`#ms`) | 72 | 0 |
| type d'union | 131 | 0 |
| source de famille | 114 | 0 |
| `#src` des conjoints écrits sur la ligne `fam` (480) | 480 | 0 |
| date, lieu, divorce, séparation | 0 | 0 |

Restent des écarts expliqués, qui ne sont pas des bugs de lecture :

- 58 conjoints `? ?` : GeneWeb crée une personne anonyme, nous non (§ 4.6) ;
- 2 familles aux sexes incohérents, que `gwc` signale lui-même.

## 3. Points ouverts en cours : diagnostiqués, piste définie

### 3.1 Infos en ligne des enfants et des témoins (priorité 1)

**Où** : `_parse_inline_personal_info` (`gw_parser.py:3247`). Elle est appelée pour les enfants
(`gw_parser.py:2036`) et pour les témoins (`gw_parser.py:3243`). C'est la lecture par jetons déjà corrigée
sur la ligne `fam`, mais pas ici.

**Reproduction synthétique** (même résultat en mode complet et en streaming) :

```
fam DUPONT Jean + MARTIN Anne
csrc Reg_X
beg
- h Paul #occu Maire_(1850-1900) #src Acte_12 1820 #bp Ville #bs Reg\_7 1890
end
```

| Champ | Attendu (gwc) | Obtenu |
|---|---|---|
| profession | `Maire (1850-1900)` | `Maire (` |
| naissance | `1820` | `1850`, tirée de la profession |
| décès | `1890` | `0` |
| `person_source` | `Acte 12` | `Reg_X`, la source commune appliquée à tort |
| notes | (aucune) | `Source: Acte_12` |
| `birth_source` | `Reg_7` | `Reg\ 7` |

Les témoins (`wit m: P Q #occu Maire_(1850-1900) #src Reg 1820`) donnent le même résultat.

**Mesure sur la base réelle** (lignes enfant comparées au mot brut décodé, 4 220 enfants alignés) :

| Champ | Présents | Écarts | Nature |
|---|---|---|---|
| `#src` | 405 | 405 | rangé en note `Source: …` (`gw_parser.py:3502`), `person_source` vide |
| `#occu` | 1 338 | 30 | coupée à `(`, à un chiffre ou à `-` ; 24 fois la date de naissance devient fausse |
| `#bs` | 802 | 18 | 14 `\_` mal décodés, 4 tronqués |
| `#ds` | 817 | 36 | 33 `\_` mal décodés, 3 tronqués |
| `#bp`, `#dp` | 1 759, 2 025 | 0 | |

Le `#src` perdu a une seconde conséquence. `_apply_common_children_values` (`gw_parser.py:1113`) voit
`person_source` vide et applique `csrc` par-dessus la source propre de l'enfant, alors que gwc ne
l'applique qu'en l'absence de source propre.

**Piste** : étendre la lecture en mots bruts à la ligne enfant et à la ligne témoin.

1. Ajouter à `words.py` un lecteur pur des infos d'une personne, sur le modèle de `read_marriage_part` :
   il suit l'ordre de `set_infos` et renvoie une dataclass. Le brancher dans `_parse_child` et dans la
   lecture des témoins via `_line_words`. Garder la tolérance d'ordre actuelle : `gwc` impose l'ordre,
   les tests existants ne le font pas.
2. Avancer en un commit par sujet :
   1. `#src` → `person_source`, ce qui corrige aussi l'application de `csrc`. Supprimer la note
      `Source: …` après avoir vérifié qui la lit (tests, exports, application).
   2. `#occu` lu comme un seul mot.
   3. Sources décodées par `decode_word` (§ 3.3).
3. Vérifier contre deux références : le comparateur de lignes enfant, et l'oracle `gwu` étendu aux lignes
   enfant, ce qui couvre aussi les 2 721 conjoints non comparés (§ 1.3).

### 3.2 Qualificatif placé avant le `+`

**Symptôme** : `fam DUPONT Jean #banns mf + MARTIN Anne` ou `fam DUPONT Jean #pacs + MARTIN Anne` :
l'épouse est perdue (`wife_id` à `None`). `#banns +` sans code fonctionne
(`test_qualificatif_avant_le_plus_reste_lu`).

**Cause** : `_parse_personal_info` (`syntax.py:185`) accepte avant le `+` les jetons `BANNS`, `CONTRACT`,
`NSCK`, `NSCKM`, `NOMENT` et `LICENSE`. Il n'accepte ni le code de sexe qui les suit, ni `#pacs` /
`#residence` (lexés `UNKNOWN "#"` + identifiant). Le nœud est coupé avant le `+`.

**Contexte** :

- cet ordre est hors de la grammaire de `gwc`, qui attend les qualificatifs après le `+` ;
- la base réelle n'en contient aucun ;
- un test écrit pendant `2cef062` a été retiré, faute de correctif dans ce commit.

**Décision à prendre** : compléter la tolérance ou la retirer. Je recommande de la compléter, car elle
existe déjà pour les mêmes balises, et une tolérance partielle perd des données sans prévenir. Concrètement :
dans `_parse_personal_info`, consommer un code de sexe facultatif (`est_code_sexe`) et accepter
`UNKNOWN "#"` + `EVENEMENTS_UNION` ; dans la branche `UNKNOWN "#"` de `_parse_family_line`, ajouter le
qualificatif.

### 3.3 Stockage de `_` et de `\_`

État actuel, vérifié sur fixtures synthétiques :

| Champ | Stockage |
|---|---|
| `birth_place`, `death_place`, `marriage_place` | mot brut (`Ville_A`) |
| `marriage_source`, `person_source` (ligne `fam`) | mot brut |
| `birth_source`, `death_source`, `burial_place`, `burial_source`, `occupation` | décodé par `replace("_", " ")` (20 occurrences dans `gw_parser.py`) |

Il y a deux défauts :

- le lieu d'inhumation est décodé alors que les autres lieux restent bruts ;
- `replace` ne connaît pas l'échappement, donc `X\_Y` devient `X\ Y` au lieu de `X_Y`. Cela touche au
  moins 47 sources d'enfant dans la base réelle, et aussi les conjoints sur la ligne `fam`.

**Piste en deux temps** :

1. **Sans changer de convention** : remplacer `replace("_", " ")` par `decode_word` là où le code
   décode déjà. Cela corrige `\_`. C'est un commit indépendant.
2. **Choisir une convention unique**, ce qui impacte `place.py` (qui s'appuie sur `_-_`), les exports
   GEDCOM/JSON/XML, l'API et l'application. Je recommande de décoder comme `gwc` tous les champs texte,
   et de garder les lieux bruts pour `place.py`. Cela suppose de décoder aussi `marriage_source` et
   `person_source`, aujourd'hui bruts. À trancher avec l'équipe avant de toucher aux exports.

### 3.4 Généraliser la lecture en mots bruts

Le pilote est validé par l'oracle. L'ordre proposé :

1. lignes enfant et témoin (§ 3.1) ;
2. infos des conjoints sur la ligne `fam`. Elles passent encore par `syntax.py` et les recolleurs : aucun
   écart sur les champs comparés, mais la lecture reste fragile. Le saut d'un `#src` mal placé dans
   `_apply_family_extra_tokens` utilise lui aussi `mot_end` ;
3. lignes `rel` et autres lignes restantes.

À la fin, supprimer les recolleurs (`mot_end`, `nom_end`, `nom_text`, `place_run_end`, `texte_libre`,
`_join_tokens_text`). Environ 1 100 lignes sont concernées. Je déconseille de réécrire le lexer : il est
partagé avec `syntax.py` (1 645 lignes), c'est plus risqué pour le même gain. À chaque étape : tests verts,
oracle dans les deux modes, un commit.

## 4. Points ouverts non débutés

### 4.1 Versionner l'outillage d'oracle (prérequis)

Les scripts n'existent que dans un répertoire temporaire de session et se perdent d'une session à
l'autre :

- `oracle_run.sh` : filtre, puis `gwc`/`gwu` dans un conteneur jetable ;
- `oracle_filter.py` ;
- `oracle_cmp.py` : familles ;
- `oracle_psrc.py` : sources des conjoints ;
- `oracle_child.py` : lignes enfant contre le texte brut.

Proposition : `core/tools/oracle/`, avec le chemin de la base en argument, un Dockerfile qui compile
GeneWeb 7.1 et des sorties toujours hors dépôt. Aucune donnée, aucun résultat nominatif n'y est versionné.
Sans cet outillage, aucun nouvel arrivant ne peut reproduire les mesures de ce document.

### 4.2 Champs lus mais non stockés

- **`#mn`** (note de mariage) : consommé, mais `Family` n'a pas de champ `marriage_note`. La base réelle
  n'en contient aucun.
- **Notes en ligne `#bn`, `#pn`, `#dn`, `#rn`** (lues par `set_infos`) : ignorées sur une ligne enfant.
  Sur la ligne `fam`, la suite des infos du conjoint est perdue :
  `fam DUPONT Jean 1820 #bp V #bn Note_N 1890 #dp W + MARTIN Anne` donne un mari sans date ni lieu de
  décès. La base réelle n'en contient aucune.

### 4.3 Sérialisation et consommateurs

- `Family.to_dict` n'écrit ni `marriage_source`, ni `family_qualifiers`, ni `common_birth_place`, ni
  `common_children_source`, ni `spouses_unknown`.
- `Person.to_dict` n'écrit pas `person_source`.
- Ces champs, alimentés depuis peu, n'ont été vérifiés ni dans les exports GEDCOM/JSON/XML, ni dans les
  modèles de l'API, ni dans l'application Streamlit.

### 4.4 Oracle au niveau des personnes

Comparer à `gwu` les infos des personnes, et pas seulement des familles : dates, lieux, professions,
titres, alias, accès, `pevt`. Il faut pour cela lire les lignes enfant de `rt.gw`. C'est l'étape de
vérification de § 3.1.

### 4.5 Différences de modèle à trancher

| Sujet | GeneWeb | `geneweb-py` |
|---|---|---|
| Conjoint `? ?` (58 cas) | personne anonyme créée | pas de personne (`spouses_unknown`) |
| `fevt` et ligne `fam` | le bloc `fevt` remplace les données de mariage de la ligne | les deux sont lus ; la réconciliation reste à vérifier |
| `wnote` | non lu par 7.0 ni 7.1 | lu |
| `comm` répétés | refusés par 7.1 | acceptés |
| `#MARR` en majuscules | non vérifié | lu comme `marr` (balises standard insensibles à la casse) |
| Sexes incohérents (2 familles) | avertissement de `gwc` | pas d'avertissement (à confirmer) |

### 4.6 Mesures non élucidées

- **Enfants sans sexe** : 8 dans le parse, contre 57 lignes `- ` sans `h`/`f` dans la mesure brute. Il est
  possible que ce soit la mesure qui se trompe.
- **Alignement des enfants** : 19 familles où le comparateur de lignes enfant ne trouve pas le même nombre
  d'enfants. C'est probablement une limite du script (blocs détachés), pas vérifiée.
- **Constructions absentes de la base** : `#eng`, `page-ext` et `wizard-note` ne sont couverts que par
  des tests synthétiques ; `rel` ne compte que 16 blocs.

### 4.7 Hors parser, mais liés

- Les 26 commits ne sont pas poussés : la décision appartient au responsable du dépôt.
- Le paquet `core` déclare `requires-python >= 3.8`, mais la CI ne teste que 3.11 à 3.13.
- La publication PyPI de `geneweb-py` est en attente.

## 5. Repères pratiques

### Commandes (depuis la racine du monorepo)

```bash
uv sync --all-packages --all-extras
uv run --package geneweb-py python -m pytest core -q                       # suite complète
uv run --package geneweb-py python -m pytest core --cov=geneweb_py         # couverture (≥ 80 %)
uv run --package geneweb-py ruff check core/src core/tests --ignore E501
uv run --package geneweb-py ruff format --check core/src core/tests
uv run --package geneweb-py mypy core/src/geneweb_py                       # 0 erreur à maintenir
```

### Code

| Fichier | Contenu utile |
|---|---|
| `parser/words.py` | lecteur de mots bruts, `read_marriage_part` (l. 96) |
| `parser/gw_parser.py` | `_tokens_line_text` (105), `_line_words` (145), `_apply_marriage_part` (193), `_parse_family_block` (937), `_apply_common_children_values` (1113), `_apply_family_extra_tokens` (1128), `_parse_family_line` (1309), `_parse_child` (1952), `_parse_inline_personal_info` (3247) |
| `parser/syntax.py` | `FamilyBlockParser` (83), `_parse_personal_info` (185), `_parse_marriage_modifiers` (425) |
| `parser/place_tokens.py` | recolleurs `place_run_end` (35), `mot_end` (118), `nom_end` (146), `nom_text` (161) ; `QUALIFICATIFS_UNION`, `EVENEMENTS_UNION` |
| `parser/streaming.py` | `source_text`, conservé pour les lecteurs de ligne brute |
| `family.py` | `FamilyQualifier`, `MarriageStatus`, `Family` |

Les numéros de ligne sont ceux de `30fd986` ; ils bougeront.

### Tests ajoutés ou modifiés par l'audit (`core/tests/`)

- **Ligne `fam`** : `unit/test_fam_line_*.py`
  - `burial_occupation`, `compound_names`, `death_markers`, `marriage_part`, `marriage_source` ;
  - `person_source`, `relation_sex_code`, `relation_status`, `spouse_fields`, `spouse_places`.
- **Lecteur de mots** : `unit/test_words.py`.
- **Enfants** : `unit/test_common_children_place_source.py`, `fixtures/simple_family.gw`.
- **Événements** : `unit/test_fevt_line_fields.py`, `unit/test_pevt_missing_date_keeps_known.py`,
  `unit/test_custom_event_tags.py`.
- **Texte libre** : `unit/test_free_text_lines_verbatim.py`, `unit/test_notes_block_verbatim.py`,
  `unit/test_metadata_header_notesdb.py`.
- **Divers** : `unit/test_unknown_name_placeholders.py`, `unit/test_streaming_token_parity.py`,
  `unit/test_parser_improvements.py`, `integration/test_gw_parser.py`.

## 6. Règles du dépôt à respecter

- **Le dépôt est public.** Aucun fichier `.gw`/`.ged` réel, et aucun nom, lieu ou date de vraie personne
  dans le code, les tests, la documentation ou les messages de commit, historique compris.
  - Fixtures synthétiques uniquement (`DUPONT Jean`, `MARTIN Anne`…).
  - Une base réelle reste hors dépôt, en lecture seule (emplacement prévu : `~/code_dev/TOLDOT/_local_testdata/`).
- **Python passe uniquement par `uv`** : pas de `pip`, `poetry` ni `conda`.
- **Qualité** : mypy strict à 0 erreur, couverture ≥ 80 %, ruff propre. Le paquet `core` reste compatible
  Python 3.8 (pas de syntaxe 3.10+ dans `core/src`).
- **Commits** : un sujet par commit, en anglais (`fix(parser): …`). Ajouter les chemins explicitement
  (jamais `git add -A`), puis vérifier `git diff --cached --name-only`. Aucun `git push` ni `--force`
  sans accord explicite.
- **Langue** : documentation et échanges en français ; code et identifiants en anglais.

## 6. Mesures

### 6.1 Ligne de base de la phase 0 (2 novembre 2026, avant toute correction de la finalisation)

Commande : `core/tools/oracle/run.sh "$GENEWEB_REAL_BASE" <sortie>` puis
`core/tools/oracle/compare.py "$GENEWEB_REAL_BASE" <sortie>/rt.gw [--stream]`. Oracle : GeneWeb officiel
`v7.1.0-beta2`. Base : le grand arbre (2 875 familles, 6 353 blocs `pevt`, 2 685 blocs `fevt`). Le filtre retire
97 lignes `wnote` et 30 `comm` répétés, et **ne retire plus les blocs `fevt`**. `gwc` et `gwu` terminent sans
erreur ; `gwu` réécrit 2 875 familles. Les tableaux des modes complet et streaming sont identiques.

Taux = champs identiques entre notre lecture de la source et notre lecture de `rt.gw`, divisés par les champs
non vides chez `gwu`. « Encore bruts » = valeurs lues qui contiennent encore un `_` (décodage à faire, § 3.3).

| champ | présents (gwu) | identiques | écarts | encore bruts | taux |
|---|---|---|---|---|---|
| fam.divorce | 0 | 0 | 0 | 0 | n/a |
| fam.family_source | 306 | 306 | 0 | 302 | 100.0 % |
| fam.kind | 370 | 215 | 155 | 0 | 58.1 % |
| fam.marriage_date | 1872 | 1739 | 133 | 2 | 92.9 % |
| fam.marriage_place | 1776 | 1626 | 150 | 1714 | 91.6 % |
| fam.marriage_source | 783 | 743 | 40 | 297 | 94.9 % |
| fam.witnesses | 237 | 224 | 13 | 0 | 94.5 % |
| fevt.place | 2022 | 2022 | 0 | 2008 | 100.0 % |
| fevt.source | 885 | 885 | 0 | 367 | 100.0 % |
| fevt.witnesses | 331 | 331 | 0 | 0 | 100.0 % |
| pers.baptism_date | 28 | 28 | 0 | 0 | 100.0 % |
| pers.baptism_place | 25 | 25 | 0 | 0 | 100.0 % |
| pers.baptism_source | 13 | 13 | 0 | 0 | 100.0 % |
| pers.birth_date | 6923 | 6922 | 1 | 0 | 100.0 % |
| pers.birth_place | 4785 | 4785 | 0 | 4738 | 100.0 % |
| pers.birth_source | 1023 | 1023 | 0 | 0 | 100.0 % |
| pers.burial_place | 172 | 172 | 0 | 0 | 100.0 % |
| pers.burial_source | 58 | 58 | 0 | 0 | 100.0 % |
| pers.death_date | 5938 | 5937 | 1 | 0 | 100.0 % |
| pers.death_place | 3147 | 3147 | 0 | 3110 | 100.0 % |
| pers.death_source | 1165 | 1165 | 0 | 0 | 100.0 % |
| pers.occupation | 2496 | 2496 | 0 | 0 | 100.0 % |
| pers.person_source | 489 | 489 | 0 | 430 | 100.0 % |
| pevt.place | 9236 | 9236 | 0 | 9147 | 100.0 % |
| pevt.source | 2641 | 2641 | 0 | 965 | 100.0 % |
| pevt.witnesses | 595 | 595 | 0 | 0 | 100.0 % |

- familles non appariés : 0
- personnes non appariés : 0
- événements non appariés : 209

contrôle naïf (rt.gw) : #bp=3394, #bs=1027, #dp=3147, #ds=1168, #occu=2723, #src=938, #mp=1776, #ms=783, wit=2787

### 6.2 Lecture

- **Famille, ligne + `fevt` (les écarts qui comptent)** : type de mariage 58,1 %, date 92,9 %, lieu 91,6 %,
  source 94,9 %, témoins 94,5 %. Tout vient de la règle de réconciliation de `gwc` (conception § 5.3) : quand
  un bloc `fevt` existe, `gwc` le fait foi, et nous gardons la valeur de la ligne. Contre-épreuve : le rejeu
  de la mesure de l'audit (copie sans blocs `fevt`) redonne **0 écart sur tous les champs de la ligne `fam`**
  (type, date, lieu, source, témoins, source de famille), 2 875 familles appariées. Les sources de mariage
  perdues (40) ont pour la plupart la forme d'une URL.
- **Personnes et événements : à lire avec prudence.** `rt.gw` est relu par notre propre parser, donc un défaut
  de lecture partagé (infos en ligne des enfants) y est invisible : les lignes `pers.*` et `pevt.*` sont à
  100 % en partie par construction. Le contrôle naïf (découpage sur les espaces de `rt.gw`) est la seule
  mesure indépendante : 938 `#src` contre 489 sources de personne lues, 2 723 `#occu` contre 2 496
  professions lues. L'ordre de grandeur (environ 450 sources, 230 professions) correspond aux pertes
  décrites en § 3.1 (infos en ligne des enfants).
- **Événements non appariés : 209** (clé type + date), contre 3 005 sur la copie sans `fevt` : la différence
  est ce que `gwu` synthétise depuis les lignes. À analyser en phase 1.
- **Dates de personne** : un écart de naissance et un de décès, à examiner.
- **Base de comparaison pour les phases suivantes** : ce tableau. Chaque phase le rejoue et le publie ici.
