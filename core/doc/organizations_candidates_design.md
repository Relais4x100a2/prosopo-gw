# Organisations candidates : conception

Document de conception validé avec l'auteur du projet (novembre 2026). Il couvre deux chantiers
indépendants, à mener dans cet ordre :

1. **Chantier A** : onglet « Organisations » de la webapp, exports du fichier compagnon et des CSV,
   documentation de la validation. Utile seul, sans LLM.
2. **Chantier B** (abandonné en novembre 2026, voir § 8) : application Streamlit, couche « fournisseur LLM » unique (OpenRouter, OpenAI,
   Anthropic, Mistral, Google AI Studio, Qwen, Ollama), réparation de DSPy 3, pont avec le fichier
   compagnon. Prérequis de la « voie 1 » de validation.

Chaque chantier a son propre plan de mise en œuvre.

> **Mise à jour (novembre 2026)** : les boutons d'export décrits ici (`.org.json`, `organisations.csv`, `liens_organisations.csv`) ont été remplacés
> par un téléchargement unique, `prosopo-<base>-<AAAA-MM-JJ>.zip`, qui contient les mêmes données
> (`base.org.json`, `csv/organisations.csv`, `csv/liens.csv`, `csv/experiences_proches.csv`).
> Voir [`exports_design.md`](exports_design.md). Les routes d'API historiques restent servies.

## 1. Intention

Les événements d'une base GeneWeb contiennent des organisations implicites : un événement
personnalisé `#Membre_Cercle_Philatelique`, une Profession ou une Éducation dont le lieu est
`[Usine_Martin]_-_Roubaix`, un métier écrit « comptable à la Banque X ». La webapp doit les **faire
apparaître** pour qu'un historien voie d'un coup d'œil qui est relié à quoi. Elle **propose** ; elle ne
décide rien, ne retient rien au-delà de la session, et ne touche jamais au `.gw`. La validation se
fait ensuite dans l'application Streamlit du dépôt ou dans les outils habituels de l'utilisateur.

### Objectifs

- Un onglet « Organisations » qui liste des **regroupements** reliant au moins deux personnes.
- Un fichier compagnon `.org.json` et deux CSV téléchargeables depuis l'onglet Export.
- Une documentation claire de l'étape suivante : valider et enrichir, avec quels outils et comment.
- Le moteur de déduction (`core/`) nomme mieux les organisations : le nom personnalisé partagé
  l'emporte sur le complément du lieu.
- Le moteur lit aussi les **événements typés** (Profession, Éducation, Diplôme, Adhésion,
  Hospitalisation, service militaire, Élection, Ordination) et le **texte des professions** :
  l'établissement est l'organisation, le type d'événement ou le métier donne le rôle.

### Non-objectifs (cette fois)

- Validation humaine dans la webapp (cocher, fusionner, renommer) : la session est éphémère, un
  travail de validation perdu au bout d'une heure serait frustrant.
- Rapprochement par témoins communs entre tags voisins (seconde étape, voir § 9).
- Événements « Autre » des **familles** (`fevt`) : ignorés par les règles, comme aujourd'hui.
- Dépôt d'un `.org.json` avec le `.gw` à l'ouverture de session.

### Anti-objectifs

- Inventer des institutions : un mot de relation (amitié, collaboration) ne fait pas une
  organisation. Une proposition douteuse doit être marquée « à revoir », jamais présentée comme sûre.
- Afficher un score de confiance comme information principale : sur une base réelle, toutes les
  propositions actuelles ont la même confiance (0,7), le tri par confiance ne dit rien.
- Réécrire le `.gw`.

## 2. Ce qu'on sait d'une base réelle

Mesures faites en local, en lecture seule, sur une base d'environ 5 800 personnes (effectifs seuls) :

| Mesure | Valeur |
|---|---|
| Événements « Autre » personnels (`oth`) | 454 |
| … avec une proposition par les règles actuelles | 224, toutes par le complément du lieu, confiance 0,7 |
| … sans proposition | 230 |
| Organisations créées après dédoublonnage | 91 (163 liens) |
| Tags distincts | 229 ; 19 portés par au moins deux personnes, couvrant 244 événements |
| Mots distincts dans les tags | 480 ; 13 vus au moins cinq fois |
| Événements « Autre » avec au moins trois témoins | 30 |
| Événements « Autre » familiaux | 36 |

Conséquences : parmi les « Autre », le regroupement par **tag partagé** est la source principale ; le
complément de lieu est une source secondaire (peu d'utilisateurs le saisissent) ; les témoins sont
un **marqueur**, pas un critère d'entrée.

Les **événements typés** sont une source distincte et plus riche (même base) :

| Type | Événements | avec lieu | avec complément de lieu | avec note |
|---|---|---|---|---|
| Profession (`occu`) | 224 | 183 | 87 (82 distincts, 5 partagés) | 194 |
| Éducation (`educ`) | 36 | 30 | 25 (20 distincts, 4 partagés) | 24 |
| Diplôme (`grad`) | 11 | 8 | 5 | 10 |
| Service militaire (`mser`) | 6 | 5 | 1 | 3 |
| Élection (`elec`) | 5 | 4 | 1 | 5 |
| Adhésion, Diplôme obtenu, Hospitalisation, Ordination, Démobilisation | 1 à 3 chacun | | | |
| Résidence (`resi`) | 663 | 649 | 503 (456 distincts) | 63 |
| Recensement (`cens`) | 38 | 37 | 35 | 3 |

Le complément de lieu d'une Profession ou d'une Éducation est presque toujours un établissement
(40 % et 70 % des événements en ont un, contre 5 % des « Autre »). Celui d'une Résidence ou d'un
Recensement est une adresse (rue, hameau, maison) : **exclu**.

L'**attribut profession** de la personne (`#occu`, hors événement) : 2 318 personnes, 1 338 valeurs
distinctes, 211 partagées. Textes courts (deux tiers font moins de trois mots) ; 238 contiennent
« à / au / à la », 172 un mot d'établissement, 408 une virgule (plusieurs métiers ou précisions).

L'auteur du projet saisit l'employeur tantôt dans le complément de lieu, tantôt dans le texte du
métier après « à », et rappelle qu'il n'est pas représentatif de tous les utilisateurs : les deux
formes doivent être lues.

## 3. Règles de déduction (chantier A, `core/`)

Le module `core/event_to_organization.py` évolue ; les tests existants restent verts ou sont adaptés
en conséquence.

### 3.1 Ce qui compte comme candidat

Un regroupement est **candidat** s'il relie **au moins deux personnes distinctes**. Le moteur peut
créer des organisations à une seule personne (elles existent déjà aujourd'hui), mais l'API, l'onglet
et les exports ne montrent que les candidats. Le « reste à classer » reçoit tout événement « Autre »
personnel qui n'aboutit pas à un candidat : sans proposition, ou dont l'organisation ne relie
qu'une personne.

Aujourd'hui le moteur fait l'inverse de § 3.2 : le complément de lieu l'emporte sur le tag
(`propose()`, branche `if complement:` avant `elif tag_name:`). C'est ce qui change.

Les § 3.2 à 3.4 concernent les événements « Autre » ; § 3.6 et 3.7 les événements typés et les
textes de profession ; § 3.8 leur réunion.

### 3.2 Nommer un regroupement « Autre », par ordre de priorité

1. **Le complément du lieu** `[Complément]_-_Ville`, **s'il contient un mot d'établissement**
   (§ 3.4 : usine, société, entreprise, atelier, établissement, école, lycée, couvent…). Il
   l'emporte alors sur le tag : `#Cours_peinture … [Atelier_Rose]_-_Lyon` donne « Atelier Rose ».
   `metadata["named_from"] = "place"`.
2. **Sinon, le nom personnalisé (tag), s'il dit plus qu'un rôle.** Le tag est découpé par
   `_split_tag` : préfixe de rôle (`Membre`, `Élève`…) + reste. Il « dit plus qu'un rôle » si le
   reste est non vide, ou s'il n'a aucun préfixe de rôle connu (`Cercle_Philatelique`,
   `Capitaine_de_navire`). Le nom est le reste (ou le tag entier), mots séparés, chiffres retirés.
   `metadata["named_from"] = "tag"`.
3. **Sinon, « à déterminer », avec l'extraction la plus probable** : s'il reste un complément de
   lieu (sans mot d'établissement), il sert de nom ; l'organisation est marquée
   `needs_review = True`, `metadata["to_determine"] = True`, `metadata["named_from"] = "place"`.
4. **Sinon** (ni complément ni tag nommant quelque chose, ex. `#Membre_1900`), rien.

Dans tous les cas, le rôle du préfixe va dans `role` du lien, la ville dans `place`, et la source
écartée (complément ou tag non retenu comme nom) est conservée dans `metadata["complement"]` ou
`metadata["tag"]`, jamais dans les alias.

### 3.3 Confiance et type

> **Mise à jour (novembre 2026)** : voir [`shared_experiences_design.md`](shared_experiences_design.md) — les actes d'état civil sont écartés d'office, un tag libre seul ne suffit plus, un mot d'établissement vaut 0,8 et les adresses sont une source.

| Cas | Confiance | Type |
|---|---|---|
| 1. Complément de lieu contenant un **mot d'établissement** (§ 3.4), avec ou sans tag | 0,8 | celui du mot |
| 2. Tag avec préfixe de rôle et reste nommant l'organisation | 0,8 | celui du mot d'établissement du tag s'il y en a un, sinon celui de la règle de préfixe |
| 2. Tag sans préfixe de rôle, partagé par ≥ 2 personnes | 0,5, `needs_review = True` | celui du mot s'il y en a un, sinon `other` |
| 3. « À déterminer » : complément sans mot d'établissement, tag qui ne nomme rien (ou tag sans préfixe porté par une seule personne) | 0,5, `needs_review = True`, `to_determine` | celui de la règle de préfixe s'il y en a une, sinon `other` |
| Tag sans préfixe de rôle, une seule personne, sans complément | pas de proposition | |
| Ni complément ni tag nommant quelque chose | pas de proposition | |

Le seuil `REVIEW_THRESHOLD = 0.7` ne change pas.

Pour connaître le nombre de personnes partageant un tag, `apply()` compte d'abord les tags par
personne distincte sur toute la généalogie, puis passe ce comptage à `propose()` (nouveau paramètre
optionnel, par défaut vide, pour ne pas casser les appels existants).

### 3.4 Vocabulaire

Deux listes de mots, comparées sans casse ni accents (`_fold`), sur chaque mot du tag ou du
complément de lieu. Elles sont des constantes publiques du module, extensibles comme
`DEFAULT_PREFIX_RULES`.

- **Mots d'établissement → type** (liste de départ, à compléter par le développeur) :
  usine, société, entreprise, compagnie, manufacture, atelier, magasin, maison, banque, établissement,
  agence, boutique, comptoir, fabrique, filature, bureau, étude, commandite, Cie, et les formes
  `SNC`, `SARL`, `SA`, `SAS`, `Et.` écrites telles quelles → `company` (voir `shared_experiences_design.md` § 3.2 bis) ;
  école, collège, lycée, université, institut, académie, conservatoire → `school` ;
  association, club, cercle, syndicat, fédération, comité, amicale, loge → `association` ;
  mairie, conseil, chambre, tribunal, préfecture, ministère, hôpital, hospice → `institution` ;
  paroisse, diocèse, abbaye, couvent, consistoire, synagogue, temple → `religious` ;
  régiment, bataillon, compagnie (si suivi d'un numéro), armée, garde → `military`.
- **Mots de relation** : amitié, collaboration, correspondance, rencontre, voisinage. Un tag qui en
  contient donne un candidat de type `other` marqué `needs_review = True`, avec la note
  `"relation"` dans `Organization.notes`, pour que l'interface le range à part (« cercle »).

Le mot déclencheur est conservé dans `Organization.metadata["trigger"]` ; la source du nom
(`"tag"` ou `"place"`) dans `Organization.metadata["named_from"]`.

### 3.5 Marqueur « collectif »

Un candidat est **collectif** si au moins un de ses événements d'origine a trois témoins ou plus.
C'est calculé côté API à partir des événements (le modèle `Organization` ne change pas pour cela).

### 3.6 Événements typés : l'établissement est dans le complément de lieu

Règle distincte de celles des « Autre » : ici le **type de l'événement donne le rôle**, et
l'organisation est l'établissement. Elle s'applique aux événements personnels dont le lieu a un
complément `[Complément]_-_Ville`, pour les types de cette table (constante publique
`TYPED_EVENT_RULES`, extensible comme `DEFAULT_PREFIX_RULES`) :

| Type d'événement | Type d'organisation par défaut | Rôle du lien |
|---|---|---|
| Profession `occu` | `company` | le texte du métier (première note de l'événement, sinon l'attribut profession de la personne, sinon « employé ») |
| Éducation `educ` | `school` | « élève » |
| Diplôme `grad`, Diplôme obtenu `degr` | `school` | « diplômé » |
| Adhésion `adhe` | `association` | « membre » |
| Hospitalisation `hosp` | `institution` | « patient » |
| Service militaire `mser`, Démobilisation `demm` | `military` | « soldat » |
| Élection `elec` | `institution` | « élu » |
| Ordination `ordn` | `religious` | « ordonné » |

Nom = complément de lieu ; lieu = ville ; date = celle de l'événement ; confiance 0,8 ; un mot
d'établissement (§ 3.4) présent dans le complément **remplace** le type par défaut (un `occu` à
« [Lycée X] » donne `school`). `metadata["named_from"] = "typed_event"`.

**Jamais** : Résidence, Recensement, et tout type absent de la table. Un complément vide ne donne rien
(le texte du métier seul n'est pas une organisation, voir § 3.7).

### 3.7 Texte de profession : « métier à / chez X »

Deux textes sont lus : l'**attribut profession** de la personne et la **note** d'un événement
Profession, quand l'événement n'a pas de complément de lieu ou que ce complément ne contient aucun
mot d'établissement (la note prime alors si elle en nomme un ; sinon le complément reste l'organisation). Le texte est découpé à la première virgule (seule la première
partie est lue, les suivantes sont d'autres métiers ou des précisions) et coupé en
`rôle` + `préposition` + `X` sur la première occurrence de « à », « au », « aux », « à la »,
« à l' », « chez », « de la », « du », « des », « de l' », « pour ».

`X` est retenu comme organisation seulement si **l'une** de ces conditions tient :

- `X` contient un mot d'établissement (§ 3.4), qui fixe le type ; ou
- la préposition est « chez » (un employeur nommé), type `company`, confiance 0,5, `needs_review`.

Sinon rien : « cultivateur à » + village, « instituteur », « employé de commerce » restent des
métiers. Nom = `X` ; rôle = la partie avant la préposition ; lieu = ville de l'événement
Profession s'il y en a un, sinon aucun ; date = celle de l'événement, sinon aucune (l'attribut
n'est pas daté) ; confiance 0,7 avec mot d'établissement ; `metadata["named_from"] = "occupation_text"`.

**Entreprise nommée sans préposition.** À défaut (ou quand `X` se termine par elle :
« directeur à Lyon des Établissements X »), chaque partie du texte, virgules comprises, est
cherchée pour un mot d'entreprise sans ambiguïté (§ 3.2 bis : société, Cie, compagnie, usine,
banque, comptoir, établissement(s), entreprise, manufacture, fabrique, filature, agence).
Le nom part de ce mot et s'arrête à « à » (le lieu) ; « usine - X » donne « X ». Le mot doit être
suivi d'un nom : « employé de banque », « directeur d'usine », « administrateur de société »,
« directeur de filature à Lille » et « directeur de banque et conseiller » ne nomment rien. Une
profession militaire (capitaine, infanterie, grenadiers…) n'en tire aucune « compagnie ». Rôle =
ce qui précède le mot, sans les mots de liaison (sinon la première partie du texte) ; un « à
ville » dans le rôle devient le lieu. Ces entreprises, nommées comme telles, sont candidates dès
une personne.

Le lien issu de l'attribut profession porte `source_event_type = "occu_attr"` et pas d'identifiant
d'événement. Un **métier partagé seul** (« instituteur » × 40) ne fait jamais une organisation.

### 3.8 Fusion entre sources

Les trois sources (« Autre », événements typés, texte de profession) alimentent le même ensemble
d'organisations : `Organization.create(name, place)` dérive l'identifiant du nom replié et de la
ville, donc « [Usine Martin] - Roubaix » venu d'un `occu` et d'un « Autre » fusionne. Le
dédoublonnage des liens existant (même personne, même organisation, même événement) est conservé ;
une même personne reliée par deux événements différents a deux liens. Le seuil « au moins deux
personnes » (§ 3.1) s'applique à l'ensemble fusionné.

### 3.9 Découpage par ville et mots ignorés (suites du chantier A)

> **Mise à jour (novembre 2026)** : voir [`shared_experiences_design.md`](shared_experiences_design.md) — la liste des mots ignorés est vide par défaut ; l'état civil est écarté automatiquement.

- **Un tag, une ville, une organisation.** Un même tag employé dans deux villes donne deux
  organisations distinctes (décision de l'utilisateur, novembre 2026) : un « Cercle » à Lille et un
  « Cercle » à Roubaix sont a priori deux organisations différentes, même si chacune peut alors
  rester sous le seuil de deux personnes.
  La ville est le lieu sans son complément `[…]`, coupé à la première virgule (`place_city`,
  `ParsedPlace.city`) : « [Usine] - Lille, Nord » et « Lille » désignent la même ville. La même
  règle sert au comptage des lieux de l'onglet Stats.
- **Mots ignorés.** Certains tags « Autre » décrivent une situation et non un groupe (recensement,
  domicile). Un événement « Autre » dont le tag contient l'un des mots ignorés (mot entier, replié :
  sans majuscules ni accents) n'est ni candidat ni « à classer » ; il est seulement compté
  (`ignored_total`). Les événements typés et les professions ne sont pas concernés. Liste par
  défaut : `recensement`, `domicile` ; l'utilisateur peut en ajouter ou en retirer. C'est un réglage
  de **session**, côté serveur, qui s'applique à la liste, au reste à classer, à la carte Stats et
  aux trois exports. Contrôles : lettres uniquement, 40 caractères au plus, 50 mots au plus.

## 4. API (chantier A)

Nouveau routeur `api/routers/organizations.py`, préfixe `/api/v1/organizations`, protégé par la
session comme les autres. Le calcul se fait **une fois par session**, à la première demande, et
reste en cache dans `GenealogyService` (appeler `infer_organizations()` deux fois est sans effet
grâce au dédoublonnage des liens, mais inutile).

- `GET /candidates` : liste paginée (`page`, `size`, tri `sort=persons|period|name`, filtres
  `type`, `named_from`, `q` sur le nom). Chaque élément : `id`, `name`, `type`, `place`,
  `named_from` (`tag`, `place`, `typed_event`, `occupation_text` ; une organisation nourrie par
  plusieurs sources garde celle de sa première création et liste les autres dans `sources`),
  `sources` (liste des types d'événement d'origine : `oth`, `occu`, `educ`, `occu_attr`…),
  `trigger`, `confidence`, `needs_review`, `to_determine` (booléen, § 3.2 cas 3), `relation`
  (booléen), `collective` (booléen),
  `person_count`, `event_count`, `first_year`, `last_year`, `places` (distincts), `roles`
  (distincts).
- `GET /candidates/{id}` : le même objet plus `members` : `person_id`, `person_name` (résolu),
  `role`, `date`, `place`, `source_event_type`, `event_type_raw`, `witness_count`.
- `GET /unmatched` : le reste à classer, **limité aux événements « Autre »** (les métiers sans
  employeur sont des métiers, pas un reste). Groupes par mot fréquent du tag (mots de plus de trois
  lettres, repliés), triés par effectif, chaque groupe avec `word`, `count` et ses événements
  (`person_id`, `person_name`, `event_type_raw`, `date`, `place`), plafonnés à 50 par groupe. Un
  événement peut figurer dans plusieurs groupes. Les événements sans mot fréquent (mot vu une seule
  fois) forment un dernier groupe « autres ». La réponse donne aussi `ignored_total`, le nombre
  d'événements écartés par les mots ignorés (§ 3.9).
- `GET /ignored-words` et `PUT /ignored-words` (corps `{"words": [...]}`) : lire ou remplacer les
  mots ignorés de la session. La réponse renvoie la liste normalisée (repliée, dédoublonnée) ; un
  mot invalide donne une 422. Remplacer la liste vide le cache des candidats.

Exports, dans le routeur existant `genealogy` à côté de `export/{format}` :

- `GET /export/org-json` : fichier compagnon `base.org.json` (`SIDECAR_VERSION = 1`, format de
  `formats/org_sidecar.py`), **limité aux candidats** et à leurs liens.
- `GET /export/organizations-csv` : `organisations.csv`, une ligne par candidat :
  `id;nom;type;lieu;source_du_nom;sources;mot_declencheur;confiance;a_revoir;collectif;
  nb_personnes;nb_evenements;premiere_annee;derniere_annee;lieux;roles`.
- `GET /export/organization-links-csv` : `liens_organisations.csv`, une ligne par lien :
  `organisation_id;organisation;personne_id;personne;role;date;lieu;type_evenement;evenement;
  nb_temoins;statut;nom_retenu` (`type_evenement` = `occu`, `educ`, `oth`, `occu_attr`… ;
  `evenement` = le tag lisible pour un « Autre », le texte du métier pour une Profession ; les deux
  dernières colonnes vides, prêtes pour la validation au tableur).

Les CSV sont en UTF-8 avec BOM et séparateur `;`, pour s'ouvrir directement dans un Excel français.
Les noms GeneWeb y sont lisibles (`_` → espace). Les colonnes `type`, `source_du_nom`, `sources` et
`type_evenement` portent les libellés français de la webapp (« École », « Événement typé »,
« éducation », « événement libre »…), la confiance a une virgule décimale (`0,8`), et les lignes sont
triées par nom d'organisation (puis, pour les liens, par personne et année). `Cache-Control: no-store` comme les autres exports.

Les schémas Pydantic vont dans `api/models/organization.py`.

## 5. Webapp (chantier A)

### 5.1 Onglet « Organisations »

Sixième onglet, entre « Événements » et « Stats » (le test qui compte cinq onglets passe à six).
Route `#/organisations` ; une fiche s'ouvre dans le panneau latéral existant via
`#/organisation/ID`, comme les personnes et les familles.

Haut de l'onglet : une phrase d'explication (« Regroupements déduits des événements personnalisés.
Ce sont des propositions : rien n'est modifié dans votre fichier. ») et une barre : tri
(personnes ↓ par défaut, période, nom), filtre par type, filtre par source du nom, recherche.

Liste : une carte par candidat avec le nom (passé par `formatGwName`), le type en libellé français,
le lieu, « N personnes · M événements », la période « 1902–1931 », et des pastilles :
« collectif », « à revoir », « à déterminer », « cercle » (relation), le mot déclencheur, l'origine
du nom (« Nom : Lieu », « Nom : Nom personnalisé »…) et les types d'événements sources (« Source :
éducation, profession »). Un clic ouvre la fiche. Le filtre « source » de la barre porte sur
l'origine du nom.

Sous la barre, une ligne « Mots ignorés » (§ 3.9) : une pastille par mot avec × pour le retirer, un
champ pour en ajouter, et le nombre d'événements écartés. Chaque groupe du reste à classer (sauf
« autres ») a un bouton « Ignorer ce mot ». La liste est retenue dans le navigateur
(`localStorage`) et réappliquée à l'ouverture de la session suivante.

Fiche (panneau latéral) : les mêmes informations, puis la liste des membres (nom cliquable vers la
fiche personne, rôle, date, lieu, nombre de témoins), les lieux distincts, et un bloc repliable
« Pourquoi cette proposition ? » qui donne la source du nom, le mot déclencheur et la confiance.

Bas de l'onglet : section repliée « Reste à classer (N événements) », groupes par mot avec effectif ;
chaque groupe déplié liste ses événements (personne cliquable, tag lisible, date, lieu). Une phrase
explique que c'est là qu'on voit quelles règles manquent.

Vide : si aucun candidat, un message court et le « reste à classer » déplié.

### 5.2 Onglet Export

Nouveau bloc « Organisations candidates » sous les trois exports existants : un paragraphe
(ce qu'est le fichier compagnon, que le `.gw` n'est pas modifié, où valider ensuite, lien vers la
section du README), puis trois boutons : `.org.json`, `organisations.csv`, `liens_organisations.csv`.

### 5.3 Stats

Une carte « Organisations candidates : N » dans la grille, cliquable vers l'onglet. Rien de plus.

### 5.4 Contraintes

CSP `default-src 'self'` : aucune bibliothèque externe. Pas de nom réel dans les tests ni dans les
scripts de bout en bout (fixtures synthétiques). Les libellés sont en français, le code en anglais.

## 6. Documentation (chantier A)

- `README.md` et `README.en.md` : la ligne « Formats : export GEDCOM, JSON, XML, et fichier
  compagnon `.org.json` » devient exacte (le compagnon est produit par la webapp et la
  bibliothèque, pas par l'export JSON). Nouvelle section **« Valider et enrichir »** reprenant § 7.
- `core/AGENTS.md` : le routeur `organizations` et les exports dans la carte de l'architecture ;
  retirer « Export CSV … organisations » du backlog.
- Le texte de l'onglet Export renvoie à cette section du README.

## 7. Et après : valider et enrichir

Texte de référence pour le README (à adapter, pas à recopier mot pour mot).

> **Mise à jour (novembre 2026)** : la voie 1 est abandonnée avec le chantier B (§ 8). Seule la
> voie 2 est retenue.

**Voie 1 : l'application Streamlit du dépôt.** Depuis la racine : `uv sync --all-packages
--all-extras` une fois, puis `./run_app.sh` (http://localhost:8501), ou
`docker compose -f app/docker-compose.yml up -d --build`. La clé du fournisseur LLM se saisit dans
le panneau latéral et n'est jamais écrite. Pages : chargement et extraction des événements
personnalisés, annotation d'un échantillon, enrichissement par prompt, optimisation DSPy,
validation (original / prédiction, accepter ou corriger), transformation de masse, tableau de bord.
C'est la voie pour faire arbitrer par un LLM les cas que les règles n'attrapent pas. Elle dépend du
chantier B (§ 8).

**Voie 2 : ses propres outils**, à partir des deux CSV.

| Outil | Pour quoi | Méthode |
|---|---|---|
| Tableur (LibreOffice Calc, Excel, Google Sheets) | Passer en revue et trancher | Ouvrir `liens_organisations.csv`, remplir « statut » (à voir / validé / rejeté) et « nom retenu ». Trier par organisation puis par date : les lignes d'une même organisation se lisent d'un bloc. |
| OpenRefine | Fusionner les doublons | Importer `organisations.csv`, regrouper les noms (fingerprint, puis n-gram), fusionner ce qui désigne la même entité, exporter. |
| Gephi | Voir les cercles | Avec `uv sync --extra analytics`, exporter le réseau personnes–organisations en GEXF. Les organisations qui relient des personnes de familles différentes sautent aux yeux ; les isolats aussi. |
| GeneWeb | Améliorer la source | Harmoniser les tags (`#Membre_Cercle_Philatelique` plutôt que trois variantes) et compléter les lieux au format `[Complément]_-_Ville`. Au prochain chargement, la webapp regroupe mieux. Seule voie où le `.gw` change, et c'est l'utilisateur qui le fait, dans son outil. |
| Base légère (Airtable, NocoDB, Baserow) | Valider à plusieurs | Importer `liens_organisations.csv`, une vue par validateur, un champ de statut partagé. |

Le résultat validé a vocation à revenir dans un `.org.json` propre, que la bibliothèque sait relire
(`formats.org_sidecar.import_organizations`).

## 8. Chantier B : application Streamlit

> **Abandonné (novembre 2026), décision de l'auteur.** Pas de crédits pour proposer un LLM au
> public ; le nettoyage relève des outils des humanités numériques (tableur, OpenRefine, Dataiku,
> ETL), alimentés par l'archive d'export (`exports_design.md`). Le rôle de l'application Streamlit
> est à redéfinir. Section conservée pour mémoire ; l'état constaté (§ 8.1) reste exact.

### 8.1 État constaté

- Le README annonce une clé OpenRouter dans le panneau latéral ; les pages n'offrent qu'OpenAI et
  Anthropic.
- `src/dspy_optimizer.py` appelle `dspy.OpenAI` et `dspy.Claude`, qui n'existent plus dans DSPy
  3.4.1 (version installée) : la page « Optimisation DSPy » est cassée.
- La page « Enrichissement » appelle directement les SDK OpenAI et Anthropic ; la page
  « Optimisation » passe par DSPy : deux chemins vers le LLM.
- Les listes de modèles sont figées et datent de 2024.
- L'application ne lit pas le fichier compagnon.

### 8.2 Cible

Une **couche fournisseur unique**, `src/llm_provider.py`, construite sur `dspy.LM` (LiteLLM en
dessous ; aucun SDK à ajouter). Elle expose une liste de fournisseurs et une fonction qui, à partir
de (fournisseur, modèle, clé ou adresse), renvoie un `dspy.LM` configuré, plus un test de connexion
(requête d'un mot).

| Fournisseur | Variable d'environnement | Préfixe LiteLLM | Particularité |
|---|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/` | Accès à presque tous les modèles, Qwen compris ; en-têtes `HTTP-Referer` / `X-Title` conservés |
| OpenAI | `OPENAI_API_KEY` | `openai/` | |
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic/` | Déjà présent, conservé |
| Mistral | `MISTRAL_API_KEY` | `mistral/` | |
| Google AI Studio | `GEMINI_API_KEY` | `gemini/` | Clé obtenue sur aistudio.google.com |
| Qwen (Alibaba DashScope) | `DASHSCOPE_API_KEY` | `openai/` + `api_base` DashScope compatible OpenAI | Adresse par défaut à fixer par le développeur (point d'accès international), modifiable |
| Ollama | aucune | `ollama_chat/` | `OLLAMA_BASE_URL`, défaut `http://localhost:11434` ; la liste des modèles installés est lue sur `/api/tags` |

Le nom de l'ancienne variable `API_KEY_OPENROUTER` reste accepté en repli.

Panneau latéral commun (une fonction dans `src/`, appelée par chaque page qui a besoin d'un LLM) :
fournisseur ; **modèle en texte libre** avec suggestions (quelques modèles récents par fournisseur,
dans une constante facile à mettre à jour ; pour Ollama, les modèles installés) ; clé en champ
masqué préremplie depuis l'environnement, ou adresse pour Ollama ; bouton « Tester la connexion ».
La clé vit dans `st.session_state`, jamais sur disque ni dans les journaux.

Pages : « Enrichissement » et « Optimisation DSPy » passent par la couche fournisseur ; les appels
SDK directs disparaissent. `dspy.settings.configure` est remplacé par ce que DSPy 3 recommande
(`dspy.configure` ou contexte). `app/.env.example` liste toutes les variables, sans valeur.

**Pont avec le compagnon** : la page « Validation » accepte le dépôt d'un `.org.json` produit par
la webapp (ou par la bibliothèque) et présente ses candidats à la validation, à côté du flux actuel
fondé sur les `pevt`. Le détail de l'écran est laissé au développeur, avec une contrainte : le
résultat validé est téléchargeable en `.org.json` (même format, `needs_review` à `False` pour ce
qui est validé, lignes rejetées supprimées).

Tests : unitaires sur la couche fournisseur (construction des paramètres par fournisseur, variables
d'environnement, repli), sans réseau. Les tests de l'application tournent dans la CI s'ils n'y sont
pas déjà ; sinon, les ajouter est hors périmètre et à signaler.

## 9. Suites envisagées

- Rapprochement par témoins : deux événements « Autre » de personnes différentes, aux tags voisins,
  partageant une part suffisante de témoins (Jaccard sur les listes de témoins) sont probablement
  le même cercle. Calculable sans LLM ; ne concerne qu'une minorité d'événements (75 % n'ont pas
  de témoin).
- Événements « Autre » des familles.
- Dépôt d'un `.org.json` avec le `.gw` à l'ouverture de session dans la webapp.
- Validation dans la webapp si la session cesse d'être éphémère.

## 10. Ce qui est laissé au développeur

- Le découpage exact des mots et l'ordre de la liste de vocabulaire (§ 3.4), à condition de la
  garder extensible et testée.
- La liste exacte des prépositions et la gestion des élisions et de la casse dans le texte des
  professions (§ 3.7), avec des tests sur des textes synthétiques qui couvrent les faux positifs
  (« cultivateur à Trifouilly », « employé de commerce », « veuve, sans profession »).
- La pagination et le plafonnement des réponses pour rester rapide sur une base de 10 000
  personnes.
- La mise en page précise des cartes et du panneau, dans le style existant (`style.css`).
- Les noms de fonctions, les schémas Pydantic et l'organisation des tests.
- L'adresse par défaut de DashScope et les suggestions de modèles (chantier B, abandonné), à dater
  dans un commentaire.
