# Organisations probables et expériences proches : conception

Document de conception issu d'une séance de travail avec l'auteur du projet (novembre 2026), après
la mise en service de l'onglet « Organisations » (chantier A, voir
[`organizations_candidates_design.md`](organizations_candidates_design.md)). Il modifie certaines
règles de ce document ; les sections concernées sont citées. Ce qui n'est pas cité reste valable.

## 1. Intention

### Le constat

L'onglet « Organisations » est jugé peu clair, et trop chargé de propositions non pertinentes. Sur
la base réelle de référence (comptes seulement, voir § 2), une seule des 12 candidates nommées
d'après un tag libre était une vraie organisation selon l'auteur. La liste met au même niveau des
organisations quasi certaines, des hypothèses fragiles et des regroupements dus au hasard.

### Ce que l'utilisateur veut

**Une liste d'organisations très probables.** La précision passe avant l'exhaustivité : mieux vaut
une liste courte et sûre, que l'on exporte sans la retrier, qu'une liste longue à moitié fausse.

À côté, l'auteur veut voir les personnes qui ont vécu une **expérience proche** : même nature
d'événement (déportation, internement, résistance, voyage, amitié…), même période, même lieu ou
indice commun dans les notes. Après lecture d'un prototype, son verdict : ces rapprochements ne
prouvent **pas une appartenance commune**, ils signalent une **proximité**. Ce ne sont donc pas des
organisations.

### Objectifs

1. Ne jamais proposer d'organisation à partir d'un acte d'état civil.
2. Ne garder dans la liste « Organisations » que les candidates qui ont un signal fort.
3. Calculer et afficher des **expériences proches**, avec la raison de chaque rapprochement.
4. Exporter les expériences proches en CSV.
5. Rendre l'onglet lisible : deux sections, les réglages et le reste à classer repliés.

### Non-objectifs

- Conserver les expériences proches entre deux sessions : elles se recalculent à chaque chargement
  (décision de l'auteur : « affichage et export CSV seulement »).
- Les écrire dans le fichier compagnon `.org.json`, ou les verser dans l'analyse de réseau
  (`analytics`).
- « Promouvoir » une expérience proche en organisation depuis la webapp (idée mise de côté, § 9).
- Toute aide d'un LLM (chantier B).

### Anti-objectifs

- Présenter une proximité comme une appartenance. Le vocabulaire ne parle jamais de « membres »
  d'une expérience proche, mais de « personnes concernées ».
- Rapprocher deux personnes sans pouvoir dire pourquoi.
- Écarter en silence : tout ce qui est écarté est compté et le compte est affiché.

## 2. Ce qu'on sait de la base réelle de référence

Ordres de grandeur arrondis, mesurés localement sur une base réelle, hors dépôt, en lecture seule
(aucun compte exact n'est publié).

- **~370 événements « Autre »** (tags libres) au total, dont **près de la moitié** (~185) sont des actes d'état civil
  saisis comme événements libres (mariage, reconnaissance, naissance, décès…), selon l'étendue de
  la liste. Les écarter retire à lui seul la moitié du bruit.
- **Une vingtaine** d'organisations candidates :
  - **plus de la moitié** nommées d'après un tag libre (confiance 0,5) ;
  - **le tiers environ** d'après un événement typé (0,8) ;
  - **une ou deux** d'après un texte de profession (0,7).

  **La plupart** ne relient que deux personnes, et **le tiers environ** n'ont pas de ville.
- **Quelques dizaines d'événements** relèvent des cinq thèmes de la séance (déportation, internement, résistance,
  voyage, amitié). **Les deux tiers environ** ont une note, d'une vingtaine de mots une fois filtrée.
- **Notes.** Parmi **une quinzaine** de paires de personnes déportées à un an près qui partagent au moins un mot,
  **presque toutes** ne partagent que des mots courants (présents dans une à quelques dizaines des **quelque 800** notes
  d'événements de la base). **Une ou deux** seulement partagent un mot rare (5 notes au plus). Compter les mots communs
  ne suffit donc pas : il faut tenir compte de leur rareté.
- **Le prototype** de la règle du § 4 trouve **une poignée d'expériences proches**, pour la plupart de deux
  personnes, liées par le même lieu ou par un mot rare. L'auteur les juge plausibles comme expériences
  proches, pas comme organisations.

## 3. Organisations probables (modifie le chantier A, § 3.3 et § 3.9)

### 3.1 Exclusion d'office de l'état civil

Un événement « Autre » dont le tag contient un **mot d'état civil** n'est ni candidat, ni
expérience proche, ni « à classer ». Il est seulement compté (`civil_status_total`).

- Liste fixe, dans le code (`CIVIL_STATUS_WORDS`, repliée : sans majuscules ni accents) :
  `naissance`, `bapteme`, `mariage`, `divorce`, `separation`, `fiancailles`, `bans`,
  `reconnaissance`, `legitimation`, `adoption`, `deces`, `inhumation`, `sepulture`,
  `recensement`, `domicile`.
- Mots volontairement **absents** : `contrat` (un `Contrat_Engagement` ou un `Contrat_Travail` est
  légitime ; un `Contrat_de_mariage` est déjà écarté par `mariage`) et `publication` (une
  publication peut être un ouvrage ; `Publication_des_bans` est déjà écarté par `bans`). Règle
  générale : un mot n'entre dans cette liste que s'il désigne un acte d'état civil **à lui seul**.
- Même correspondance que les mots ignorés (§ 3.9 du chantier A) : mot entier, replié.
- Ce n'est pas un réglage : l'utilisateur ne peut pas retirer ces mots. Les mots ignorés de
  l'utilisateur s'y ajoutent. `recensement` et `domicile` passent donc de la liste par défaut des
  mots ignorés à cette liste fixe ; la liste par défaut des mots ignorés devient vide.
- Les événements typés (y compris les naissances, mariages et décès GeneWeb) ne sont pas concernés :
  ils ne passaient déjà pas par les règles « Autre ».

### 3.2 Ce qui reste une organisation

Une candidate n'entre dans la liste « Organisations » que si elle a **au moins un signal fort** :

| Signal | Origine (règles du chantier A) | Confiance |
|---|---|---|
| Événement typé (éducation, profession…) | § 3.6 | 0,8 |
| Complément de lieu contenant un mot d'établissement | § 3.2 cas 1 | 0,8 |
| Tag avec préfixe de rôle et reste nommant l'organisation (`Membre_Cercle_X`) | § 3.2 cas 2 | 0,8 |
| Tag contenant un mot d'établissement | § 3.2 cas 2 | 0,8 |
| Tag ou complément contenant un **mot de voie** suivi ou précédé d'un numéro (adresse) | nouveau | 0,7 |
| Texte de profession « métier à / chez X » avec mot d'établissement | § 3.7 | 0,7 |
| Complément de lieu sans mot d'établissement (« à déterminer ») | § 3.2 cas 3 | 0,5, `needs_review` |

Mots de voie (`STREET_WORDS`, repliés) : `rue`, `passage`, `avenue`, `boulevard`, `place`,
`impasse`, `quai`, `chemin`, `allee`, `cours`, `square`, `villa`, `cite`.

Détection d'une adresse, sur le texte replié, `_` remplacés par des espaces, découpé en mots :

1. le texte contient un mot de voie ;
2. le **numéro d'immeuble** est le **premier ou le dernier mot** du texte (une virgule avant le
   numéro final est admise) : un nombre d'au plus quatre chiffres, éventuellement suivi de `bis`,
   `ter` ou `quater` (« 7 passage X », « 12 bis rue Y », « passage X, 7 ») ;
3. un nombre placé **au milieu** du texte n'est jamais un numéro : il fait partie du nom de la voie
   (« rue du 14 Juillet », « place du 11 Novembre ») ;
4. un nombre en première ou dernière position **suivi ou précédé d'un nom de mois** n'est pas un
   numéro (« 8 Mai avenue », « avenue du 8 Mai »).

Exemples de tests : `Passage_Fictif_7` et `7_passage_Fictif` sont des adresses ;
`Rue_du_14_Juillet`, `Avenue_du_8_Mai` et `Place_du_11_Novembre` n'en sont pas ;
`Rue_du_14_Juillet_3` en est une (numéro 3). Une adresse donne une organisation de type `other`,
`named_from = "address"`, pastille « adresse ».

**Ce qui ne crée plus d'organisation** : un tag sans préfixe de rôle, sans mot d'établissement ni
adresse, même partagé par deux personnes ou plus (ancienne ligne « Tag sans préfixe de rôle,
partagé par ≥ 2 personnes », confiance 0,5), ainsi que les tags de relation (`RELATION_WORDS` :
amitié, collaboration…). Ces événements vont à la recherche d'expériences proches (§ 4). S'ils n'y
aboutissent pas, ils vont au « reste à classer ».

Le moteur `EventToOrganizationMapper` peut continuer à produire ces propositions faibles (utile à
`Genealogy.infer_organizations()` et aux appels existants) ; c'est l'index des candidates
(`build_candidate_index`) qui ne les retient plus. Le choix de l'endroit exact est laissé au
développeur, à condition que l'API, l'onglet et les trois exports d'organisations soient cohérents.

## 4. Expériences proches

### 4.1 Ce qu'on rapproche

Entrée : les événements « Autre » personnels qui ne sont **ni** d'état civil (§ 3.1), **ni**
écartés par un mot ignoré de l'utilisateur, **ni** rattachés à une organisation de la liste (§ 3.2).
Un même événement n'apparaît donc jamais à la fois dans une organisation et dans une expérience
proche.

**Thème.** Chaque événement reçoit un thème :

| Thème | Reconnu si un mot du tag (replié) commence par | Fenêtre |
|---|---|---|
| Déportation | `deport` | même année (0) |
| Internement | `intern` | même année (0) |
| Résistance | `resist` | même année (0) |
| Voyage | `voyag` | 1 an |
| Amitié et relations | un mot de `RELATION_WORDS` | 3 ans |
| Tout autre tag | le tag lui-même, replié, chiffres retirés | 1 an |

La fenêtre est l'écart maximal admis entre les **périodes** de deux événements (définies
ci-dessous). Les fenêtres des thèmes
nommés viennent de l'auteur (même année pour déportation, internement, résistance ; « quelques
années » pour l'amitié) ; celles de « Voyage » et des autres tags sont un choix par défaut.
Les thèmes connus sont une table extensible (`SHARED_EXPERIENCE_THEMES`) ; leurs préfixes ne sont
pas confondus avec un préfixe de rôle (`Membre`, `Élève`…).

**Période d'un événement.** Elle se lit sur le modèle `Date` existant, sans analyse de texte :

| Date de l'événement | Période `[début, fin]` |
|---|---|
| Date simple (`1943`, `2/3/1944`), environ (`~1943`), peut-être (`?1943`) | `[année, année]` |
| Fourchette `1942..1944` (BETWEEN) ou alternative `1942\|1944` (OR) | `[min, max]` des années de `filter_years_for_range()` |
| Avant (`<1940`) ou après (`>1940`) | aucune : l'événement est traité comme **non daté** |
| Date textuelle, inconnue, absente | aucune : **non daté** |

Les bornes ouvertes (avant / après) sont écartées par choix de précision : « avant 1940 » ne permet
pas de dire si deux personnes ont vécu la même chose au même moment.

**Écart entre deux périodes** `[d1, f1]` et `[d2, f2]` : `max(0, max(d1, d2) − min(f1, f2))`. Il
vaut 0 dès que les périodes se chevauchent. Ainsi `1942..1944` et `1943` ont un écart de 0.

**Lien entre deux événements.** Deux événements d'un même thème sont liés si :

1. ils concernent deux personnes distinctes ;
2. ils ont tous deux une période, et leur écart est inférieur ou égal à la fenêtre du thème ;
3. **et** au moins une raison :
   - **même lieu** : les deux villes (`place_city`, repliées, espaces de bord retirés) sont **non
     vides, différentes de `?`**, et égales. Deux événements sans ville ne sont **jamais** liés par
     le lieu, seulement, le cas échéant, par un mot rare ;
   - **mot rare commun** : leurs notes partagent au moins un mot rare (§ 4.2).

Un événement non daté n'est jamais lié (il est compté à part, `undated_total`).

**Expérience proche : algorithme déterministe.** Pour chaque thème, séparément :

1. Ordonner les événements du thème par `(début, fin, identifiant de la personne, rang de
   l'événement dans la personne)`. Cet ordre est l'unique ordre de parcours.
2. **Découper en tranches chronologiques.** L'étendue maximale d'une tranche est
   `E = max(1, 2 × fenêtre)`. La première tranche commence au premier événement, d'année de début
   `D`, et reçoit tous les événements suivants dont le **début** est `≤ L`, où `L` vaut d'abord `max(D + E, fin du premier événement)` puis
   s'étend à la fin de chaque événement admis (une période longue étend la tranche jusqu'à sa fin,
   sans quoi `1941..1943` et `1943` ne seraient jamais réunis). La tranche suivante
   commence au premier événement non encore placé, et ainsi de suite. Chaque événement appartient
   à exactement une tranche.
3. Dans chaque tranche, calculer les liens (règle ci-dessus) entre ses seuls événements, puis les
   composantes connexes (union-find, en parcourant les paires dans l'ordre du point 1).
4. Une composante devient une expérience proche si elle compte **au moins deux personnes
   distinctes**.
5. Tri final des expériences : thème, puis année de début, puis identifiant.

Exemple à tester : A (1940), B (1941), C (1942), D (1943), même thème de fenêtre 0, tous au même
lieu. `E = max(1, 0) = 1` : tranches {A, B} et {C, D}, mais A–B (écart 1) et C–D (écart 1)
dépassent la fenêtre 0, donc aucune expérience. Avec une fenêtre de 1 (`E = 2`) : tranches
{A, B, C} et {D} ; A–B et B–C sont liés, donc une expérience {A, B, C} ; D reste seul. Le
résultat ne dépend que de l'ordre du point 1, jamais de l'ordre de lecture du fichier.

### 4.2 Mots rares des notes

- Texte : les notes de l'événement, repliées. Mots de 4 lettres au moins, hors mots outils (liste
  courte dans le code : articles, prépositions, pronoms, « date », « annee », « mois », « jour »…).
- **Singulier naïf**, appliqué à tous les mots (notes, thème, ville) avant toute comparaison et au
  calcul des fréquences : un mot de 5 lettres ou plus perd un `s` ou un `x` final (« camps » →
  « camp », « convois » → « convoi », « travaux » → « travau » des deux côtés). Pas d'autre
  lemmatisation. Le prix accepté : de rares confusions (« cours » → « cour »), sans effet sur la
  précision puisqu'un mot ne suffit qu'à condition d'être rare.
- On retire les mots de la **ville de l'événement** et ceux du thème (« deporte », « deportation »…).
  On garde les **autres** noms de lieux : le nom d'un camp, d'une prison ou d'une ville de
  destination cité dans la note est justement un bon indice.
- Rareté : nombre de notes d'événements de la base où le mot apparaît (fréquence documentaire,
  calculée sur la généalogie chargée). Ce dictionnaire est construit **en une seule passe** sur
  toutes les notes d'événements, au moment où l'index est calculé, puis consulté en temps constant ;
  il n'est jamais recalculé par paire. Les ensembles de mots de chaque événement sont, eux aussi,
  calculés une fois. La comparaison des paires reste limitée à l'intérieur d'une tranche d'un même
  thème (§ 4.1). Un mot est **rare** s'il apparaît dans au plus
  `RARE_WORD_MAX_NOTES = 5` notes. Ce seuil est une constante, validée sur la base de référence
  (§ 2) ; sa réévaluation pour les très grandes bases est un point ouvert (§ 9).
- Les mots qui justifient un lien sont conservés pour l'affichage (au plus trois par lien).

### 4.3 Données produites

Un objet `SharedExperience` (dans `core/`, pas une `Organization`), sans persistance :

- `id` : identifiant stable dans la session (thème, période, ville, personnes) ;
- `theme` (clé) et `label` (« Déportation », ou le tag lisible pour un autre tag) ;
- `year_min`, `year_max` ;
- `places` : villes distinctes des événements ;
- `reasons` : liste de raisons distinctes, `{"kind": "same_place", "place": …}` ou
  `{"kind": "rare_word", "words": [...]}` ;
- `persons` : pour chaque événement, l'identifiant et le nom de la personne, le tag brut, l'année,
  le lieu ;
- `person_count`, `event_count`.

Un index (`SharedExperienceIndex`) contient la liste, triée par thème puis année, et les comptes
`civil_status_total`, `undated_total`. Il est calculé avec l'index des candidates, mis en cache par
le service de session, invalidé par toute écriture et par un changement de mots ignorés, exactement
comme l'index des candidates.

## 5. API (complète le chantier A, § 4)

- `GET /api/v1/organizations/shared-experiences` : `{"items": [...], "total": N,
  "civil_status_total": N, "undated_total": N}`. Pas de pagination (quelques dizaines d'entrées au
  plus) ; plafond de sécurité à 500 entrées, signalé par un champ `truncated`. `total` compte
  toutes les expériences trouvées, avant le plafond (le nombre renvoyé est la longueur de `items`).
- `GET /api/v1/organizations/unmatched` : ajoute `civil_status_total`.
- `GET /api/v1/genealogy/export/shared-experiences-csv` : `experiences_proches.csv`, mêmes
  conventions que les autres CSV (UTF-8 avec BOM, séparateur `;`, libellés français, lignes triées).
  Une ligne par événement : `experience`, `theme`, `periode`, `lieux`, `raison`, `personne`,
  `evenement`, `annee`, `lieu`. `periode` vaut `1943` ou `1942-1944` ; `raison` vaut « même lieu »
  ou « mot commun : x, y ».
- Les trois exports d'organisations appliquent les règles du § 3.

## 6. Webapp (modifie le chantier A, § 5.1 à 5.3)

### 6.1 Onglet « Organisations »

De haut en bas :

1. **Phrase d'explication** : « Organisations déduites de vos événements, et personnes ayant vécu
   une expérience proche. Ce sont des propositions : rien n'est modifié dans votre fichier. »
2. **Section « Organisations (N) »** : la barre (tri, filtres, recherche) et les cartes du chantier
   A, inchangées, avec la nouvelle pastille « adresse ».
3. **Section « Expériences proches (N) »**, avec une phrase : « Personnes ayant vécu un événement de
   même nature, à la même période, au même lieu ou avec un indice commun dans leurs notes. Ce n'est
   pas une appartenance à une organisation. » Une carte par expérience :
   - titre « Déportation · Ville · 1943 » (« lieu inconnu » s'il n'y a pas de ville) ;
   - « N personnes » ;
   - pastille de raison : « Même lieu » ou « Mot commun : x, y » ;
   - la carte se déplie sur la liste des personnes (nom cliquable vers la fiche, tag lisible, année,
     lieu). Pas de panneau latéral dédié.
   - Si aucune : « Aucune expérience proche trouvée. »
4. **Panneau replié « Réglages et événements non classés »** : la ligne « Mots ignorés » du chantier
   A, puis une phrase « N actes d'état civil écartés d'office » et « N événements sans date », puis le
   « Reste à classer » actuel.

Le vocabulaire « membres » reste réservé aux organisations.

### 6.2 Onglet Export

Le bloc « Organisations candidates » ajoute un quatrième bouton, `experiences_proches.csv`, avec une
phrase : « Personnes ayant vécu une expérience proche (non enregistré dans le fichier compagnon). »

### 6.3 Stats

La carte « Organisations candidates : N » reste ; une carte « Expériences proches : N » s'y ajoute,
cliquable vers la section.

## 7. Tests

Fixtures synthétiques uniquement (noms fictifs, lieux fictifs ou génériques). À couvrir au moins :

- état civil : `#Mariage`, `#Reconnaissance_enfant` ne donnent ni candidate, ni expérience, ni reste
  à classer, et sont comptés ; un mot d'état civil ne peut pas être retiré par l'API des mots
  ignorés ;
- organisations : un tag libre partagé par deux personnes sans autre signal ne donne plus de
  candidate ; un tag avec mot d'établissement, un tag avec préfixe de rôle et une adresse
  (`#Passage_Fictif_7`) en donnent une ;
- état civil : `#Contrat_Engagement` n'est pas écarté ; `#Contrat_de_mariage` l'est ;
- adresses : les exemples du § 3.2 (`Passage_Fictif_7` oui, `Rue_du_14_Juillet` non,
  `Rue_du_14_Juillet_3` oui…) ;
- expériences : même année et même ville → liées ; années trop éloignées → non liées ; deux
  événements **sans ville** et sans mot rare → non liés ; ville `?` des deux côtés → non liés par
  le lieu ; ville différente sans note → non liées ; ville différente avec un mot rare commun →
  liées ; mot commun mais courant (présent dans plus de 5 notes de la fixture) → non liées ;
  « camp » et « camps » → même mot ; ville de l'événement retirée des mots, autre lieu cité
  conservé ; une même personne deux fois → pas d'expérience ;
- périodes : `1942..1944` et `1943` → écart 0 ; `1940|1946` et `1943` → écart 0 ; `<1940` et
  `>1940` → non datés, comptés ; date textuelle → non datée ;
- découpage : l'exemple A–B–C–D du § 4.1 avec les fenêtres 0 et 1 ; même résultat quand l'ordre
  des personnes dans le fichier est inversé ;
- un événement rattaché à une organisation n'apparaît pas dans une expérience ;
- API et CSV (en-têtes, BOM, tri, libellés) ; cache invalidé après écriture, en session réelle
  (`create_app` + `POST /api/v1/sessions`) ;
- webapp : présence des deux sections, du panneau replié et du bouton d'export
  (`test_static_frontend.py`).

Validation sur la base réelle : locale, comptes seulement, rapportés à l'auteur sans nom.

## 8. Documentation

- Ce document, et un renvoi depuis `organizations_candidates_design.md` (§ 3.3 et § 3.9).
- README et README.en : paragraphe de l'onglet Organisations (deux sections, état civil écarté,
  expériences proches non enregistrées, export CSV).

## 9. Points ouverts et idées mises de côté

- Seuil de rareté relatif à la taille de la base (aujourd'hui fixe à 5 notes).
- Promouvoir une expérience proche en organisation (geste explicite de l'utilisateur).
- Geste « Oui / Non » sur chaque proposition, pour affiner les règles.
- Renforcer une organisation quand les notes de ses mentions partagent un mot rare.
- Rapprochement par témoins communs (§ 9 du chantier A).
- Verser les expériences proches dans l'analyse de réseau, comme liens d'un type distinct.

## 10. Ce qui est laissé au développeur

- Le découpage des mots, la liste exacte des mots outils et des mots de voie, à garder courtes,
  extensibles et testées.
- L'endroit où les propositions faibles sont écartées (§ 3.2). L'algorithme de découpage des
  chaînes, lui, est imposé (§ 4.1).
- Les noms de fonctions, les schémas Pydantic et l'organisation des modules et des tests.
- La mise en page des cartes dans le style existant (`style.css`), sans bibliothèque externe (CSP
  `default-src 'self'`).
