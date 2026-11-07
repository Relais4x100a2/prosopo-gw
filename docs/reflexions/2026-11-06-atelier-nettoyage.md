# Atelier de nettoyage : synthèse de réflexion

Statut : **réflexion en cours, rien n'est décidé** (6 novembre 2026). Ce document rassemble ce qui
existe, ce qui a été dit en discussion, les pistes et leurs conséquences, pour reprendre la
réflexion à tête reposée. Les décisions de l'auteur sont signalées comme telles ; le reste est une
proposition ou une hypothèse.

## 1. Le produit en une phrase

Un **atelier facultatif** qui aide à mettre en cohérence une base GeneWeb, par étapes et en masse,
et rend un **`.gw` corrigé** que l'utilisateur importe comme un nouvel arbre à côté de l'ancien.
Il complète la webapp de `core` et montre ce que le parser permet. Nom à trouver (l'ancien nom
« Streamlit » ne tient plus : la technique n'est pas choisie).

## 2. Ce qui existe aujourd'hui (faits)

**Moteur `core` (geneweb-py)**

- Parser `.gw` testé contre l'aller-retour GeneWeb `gwc`/`gwu` (`core/doc/parser_fidelity_audit.md`) ;
  des écarts restent ouverts (infos en ligne des enfants et témoins, qualificatif avant `+`…).
- Règles déterministes d'organisations (événements typés, mots d'établissement, compléments de lieu
  `[Complément]_-_Ville`, adresses, sociétés et formes juridiques, témoins rattachés).
- Pistes tirées des notes, « reste à classer », expériences proches.
- Exports : un zip de 16 fichiers (CSV, `base.json`, `base.sqlite`, `base.org.json`, dictionnaire,
  `LISEZMOI.txt`). Le fichier compagnon `.org.json` est relu par la bibliothèque
  (`formats.org_sidecar.import_organizations`), pas par la webapp.
- **Le moteur ne sait pas écrire de `.gw`.** Il exporte GEDCOM, JSON, XML, CSV, SQLite ; jamais `.gw`.
- Le texte source complet est conservé pendant la lecture (`GeneWebParser._source`), en mode complet
  comme en streaming : c'est un appui pour des corrections ciblées (§ 5.2).
- Aucun appel LLM : `EventToOrganizationMapper` garde un point d'extension facultatif
  (`LLMExtractorProtocol`), sans implémentation.

**Webapp de `core`** (décision de l'auteur : elle reste le produit grand public)

- Déployée sur Coolify ; fonctionne aussi en local. Sans LLM, donc sans coût d'usage.
- Sessions en mémoire, TTL glissant d'une heure, jamais persistées.
- L'utilisateur charge son `.gw`, voit stats et organisations, télécharge le zip.

**Application `app/` (ex-Streamlit)**

- Sept pages : chargement d'un `.gw`, annotation, prompt, optimisation DSPy, validation,
  transformation de masse, tableau de bord.
- Appels directs aux SDK OpenAI et Anthropic ; la page DSPy est cassée avec DSPy 3 ; aucun test dans
  la CI (seule l'image Docker est construite). Elle ne lit ni le zip ni le `.org.json`.
- Elle a été pensée pour l'enrichissement par LLM, pas pour le nettoyage guidé décrit ici.

**Documents de conception à relire**

- `core/doc/exports_design.md` § 8 (Streamlit consommateur) et § 9 (sources, TEI, rechargement du
  compagnon).
- `core/doc/organizations_candidates_design.md` § 7 (voies de validation), § 8 (chantier B), § 9.

## 3. Ce qui a été dit en discussion (6 novembre 2026)

Positions de l'auteur :

- Pas de budget pour offrir un LLM au public, et pas d'envie de gérer des crédits (« 5 € »),
  des quotas ou une surveillance.
- L'atelier est **facultatif** : d'autres moyens de nettoyer existent (tableur, OpenRefine,
  Dataiku). Il vise ceux qui n'en ont pas, ne savent pas ou n'ont pas envie.
- Ce n'est pas forcément du Streamlit : peut-être une webapp classique.
- Parcours imaginé : l'utilisateur charge ses données, puis un processus le guide :
  1. mise en cohérence des **lieux** ;
  2. mise en cohérence des **sources** (champ unique : les déplacer dans les notes, ou les garder
     dans le champ avec un délimiteur et une taxinomie cohérents) ;
  3. **organisations** : GeneWeb ne sait pas en créer ; on adopte une règle d'écriture qui les rend
     faciles à reconnaître, pour que le parser les retrouve au prochain chargement.
- Sortie : un **`.gw` corrigé**, importé comme **un autre arbre**, à côté de l'original, pour
  comparer avant de basculer. L'arbre d'origine n'est jamais remplacé.
- Une aide LLM pour les corrections est souhaitée, mais hors budget de l'auteur.
- Inquiétude : un généalogiste amateur ne saura pas installer avec Docker.
- Ne pas se lancer dans un chantier démesuré.

Propositions faites en discussion, **non validées** :

- Pas de `.gw` « pré-corrigé » dans le zip de la webapp : il appliquerait des propositions sans
  validation humaine (« pas d'inventions silencieuses »).
- Écrire le `.gw` par **corrections ciblées** sur le fichier d'origine plutôt que par régénération.
- Découper en trois chantiers : écriture du `.gw` dans `core`, conventions d'écriture, atelier.

## 4. Deux publics, deux besoins

| | Généalogiste amateur | Historien (humanités numériques) |
|---|---|---|
| Aisance technique | Faible : pas de Docker, pas de ligne de commande | Tableur, souvent OpenRefine ; parfois scripts |
| Ce qui bloque | Ne sait pas quoi corriger, ni comment réinjecter dans GeneWeb | Le temps : écrire des règles de regroupement dans OpenRefine ou Excel |
| Ce qu'il attend | Être guidé pas à pas, avec des suggestions à accepter ou refuser | Un processus cadré et rapide, des regroupements en masse, un résultat traçable |
| Sortie utile | Un `.gw` corrigé à réimporter | Un `.gw` corrigé **et** des tables propres (CSV, SQLite) pour ses analyses |
| LLM | Probablement un chatbot grand public gratuit, s'il en a un | Peut avoir une clé d'API, ou Ollama |
| Données sensibles | Peu conscient du risque d'envoyer ses données à un tiers | Soumis à des règles (personnes vivantes, RGPD, archives) |

Point commun : tous deux finissent dans GeneWeb, et tous deux ont besoin de **ne rien perdre** et
de **pouvoir revenir en arrière**.

Hypothèse : l'historien pourrait se contenter du zip actuel **si** les CSV corrigés pouvaient
revenir en `.gw` (§ 5.1, piste C). Ce chaînon manque pour tout le monde.

## 5. Les questions structurantes

### 5.1 Que produit l'atelier ?

| Piste | Description | Conséquences |
|---|---|---|
| A. `.gw` corrigé | L'atelier applique les corrections validées et rend un nouveau `.gw` | Exige un écrivain `.gw` fidèle dans `core`. Le plus utile aux deux publics. Le plus coûteux. |
| B. Journal de corrections | Liste des changements (avant / après, ligne, motif) que l'utilisateur reporte à la main dans GeneWeb | Simple à produire, mais fastidieux pour l'amateur : écarté de fait par l'auteur. Utile en complément de A, comme trace. |
| C. CSV corrigés → `.gw` | L'utilisateur corrige les CSV (tableur, OpenRefine), puis un outil relit ces CSV et produit le `.gw` corrigé | Sert l'historien sans atelier. Demande de définir quelles colonnes sont modifiables (`statut`, `nom_retenu`, un « lieu retenu »…) et de gérer les CSV abîmés par les tableurs. Même écrivain que A. |
| D. `.org.json` validé | Seulement les organisations, dans le fichier compagnon | Ne touche ni lieux ni sources ; ne revient pas dans GeneWeb. Insuffisant pour le besoin exprimé. |

Constat : A et C reposent sur **la même fondation** (appliquer des corrections à un `.gw`). B en est
un sous-produit naturel.

### 5.2 Comment écrire le `.gw` ?

| Piste | Principe | Conséquences |
|---|---|---|
| Régénération | Réécrire tout le fichier depuis le modèle objet | Tout ce que le parser ne modélise pas exactement (mise en forme, commentaires, blocs rares, écarts encore ouverts de l'audit) risque d'être perdu ou altéré sans qu'on le voie. Comparaison avec l'original difficile. |
| Corrections ciblées | Repartir du texte d'origine et ne remplacer que les passages corrigés | Le reste est recopié à l'identique ; un `diff` montre exactement les corrections. Demande de connaître la position de chaque valeur dans le texte (le texte source est déjà conservé). Contrôle possible par l'aller-retour `gwc`/`gwu` existant. |

Proposition : corrections ciblées. Conséquence : les écarts ouverts de l'audit de fidélité ne
bloquent pas, tant qu'on ne corrige que des valeurs bien localisées (un lieu, une source, un tag).

### 5.3 Que charge l'atelier : le `.gw` ou le zip ?

- Le zip est une **copie aplatie** : on ne peut pas reconstruire un `.gw` fidèle à partir de lui.
- Pour produire un `.gw` corrigé, l'atelier a besoin du **`.gw` d'origine**. Le zip peut s'y ajouter
  (pour reprendre un tri déjà fait, ou les CSV corrigés de la piste C).
- Conséquence : l'atelier charge le `.gw` ; le parcours « je charge mon zip » suppose de joindre
  aussi le `.gw`.

### 5.4 Conventions d'écriture dans GeneWeb

C'est le cœur du « pour que le parser les retrouve ». À définir une fois, documenter, et faire
reconnaître par `core` avec une confiance maximale.

- **Lieux** : le format `[Complément]_-_Ville` est déjà reconnu. Reste à choisir la forme canonique
  d'une ville (nom seul ? avec département, pays ? virgules ?) et la façon de fusionner les variantes.
- **Sources** : champ unique. Deux voies évoquées par l'auteur :
  - déplacer le texte long dans les notes et ne garder qu'une référence courte ;
  - garder la source dans le champ, avec un **délimiteur** stable entre plusieurs sources et une
    **taxinomie** (type d'acte, dépôt, cote…).
  Lien avec `exports_design.md` § 9 (décomposition `source_parent`, pistes `nature = source`).
  Conséquence : il faut vérifier ce que GeneWeb accepte et affiche correctement (caractères
  réservés, longueur, `_` et `\_`).
- **Organisations** : GeneWeb n'a pas d'entité organisation. Options : un complément de lieu
  (`[Banque Fictive]_-_Lyon`, déjà reconnu), un tag d'événement normalisé, ou une convention dans la
  note. Critères : lisible dans GeneWeb par un humain, sans ambiguïté pour le parser, stable dans le
  temps. Conséquence : une fois la convention choisie, les organisations écrites ainsi ne passent
  plus par l'heuristique, et la webapp les affiche d'emblée.

### 5.5 Forme et installation

| Piste | Pour l'amateur | Pour l'historien | Coût pour l'auteur | LLM |
|---|---|---|---|---|
| 1. Onglet « Atelier » dans la webapp existante (Coolify) | Rien à installer | Rien à installer | Hébergement déjà payé ; pas de nouveau déploiement | Pas de LLM hébergé ; voir § 5.6 |
| 2. Application locale empaquetée (exécutable ou installeur par système) | Double-clic, mais téléchargement et alertes de sécurité du système à passer | Simple | Construire et signer des paquets pour Windows, macOS, Linux ; les maintenir | Clé personnelle ou Ollama possibles |
| 3. Installation Python (`uv tool install`, ou `pipx`) | Trop technique | Accessible | Faible (dépend de la publication sur PyPI, déjà envisagée) | Clé personnelle ou Ollama |
| 4. Assistant dans un chatbot (skill Claude, GPT personnalisé, Gem Gemini) | Familier s'il a déjà un compte | Familier | Rédiger et maintenir des instructions ; pas de serveur | C'est le LLM de l'utilisateur, à ses frais |
| 5. Pas d'atelier : zip + documentation + retour CSV → `.gw` | Limité | Suffisant | Le plus faible | Hors outil |

Conséquences à garder en tête :

- **Durée des sessions.** La webapp oublie tout au bout d'une heure d'inactivité. Un nettoyage prend
  des jours. Les pistes 1 et 5 exigent donc un **fichier de travail téléchargeable** (journal des
  décisions) que l'on recharge pour reprendre. Ce fichier sert aussi de trace.
- **Données sur un serveur.** La piste 1 garde le fonctionnement actuel (le `.gw` passe par le
  serveur, en mémoire seulement). Les pistes 2 et 3 gardent tout sur la machine.
- **Un chatbot ne doit pas écrire le `.gw`.** Il peut se tromper sans le signaler et déformer le
  fichier. Dans la piste 4, il propose ; un outil déterministe applique. La piste 4 ne se suffit donc
  pas à elle-même : elle se combine avec 1 ou 5.
- **Une skill Claude** suppose un abonnement et un environnement (Claude Code, application de bureau)
  rares chez les amateurs. Un GPT personnalisé ou un Gem touche plus de monde, mais envoie les
  données à OpenAI ou Google.

### 5.6 Place du LLM

Rôle envisageable, dans tous les cas **proposer, jamais appliquer seul** : repérer les variantes
d'un même lieu, proposer des regroupements d'organisations, classer le « reste à classer », lire les
pistes des notes, suggérer une taxinomie de sources.

| Mode | Principe | Conséquences |
|---|---|---|
| Aucun | Règles et regroupements déterministes seulement (similarité de chaînes, comme OpenRefine) | Gratuit, reproductible ; couvre déjà beaucoup pour les lieux. |
| Copier-coller | L'outil prépare un lot (texte + consigne), l'utilisateur le colle dans son chatbot et recolle la réponse dans un format attendu | Aucune intégration, aucun coût pour l'auteur ; marche avec un compte gratuit. Fastidieux au-delà de quelques lots ; réponses à valider. |
| Clé personnelle | L'utilisateur saisit sa propre clé (OpenRouter, Mistral…) dans l'outil | Coût à sa charge. Dans une webapp hébergée, la clé transite par le serveur : à éviter ou appeler depuis le navigateur. |
| Local (Ollama) | Modèle sur la machine | Confidentiel et gratuit à l'usage ; réservé aux pistes locales et aux machines assez puissantes. |

Données sensibles : quel que soit le mode, envoyer des notes à un service tiers est un choix de
l'utilisateur. Un filtre (personnes vivantes, retrait des noms) peut être proposé.

## 6. Trois stratégies possibles

Elles partagent la même fondation (§ 7) et peuvent s'enchaîner.

**S1. « Tableur d'abord »** : pas d'atelier. Le zip gagne des colonnes à remplir (lieu retenu,
source retenue, organisation retenue), une notice pas à pas, et la webapp accepte en retour
`.gw` + CSV corrigés pour rendre un `.gw` corrigé.

- Pour : petit, sert l'historien tout de suite, prouve la fondation.
- Contre : l'amateur reste seul face au tableur ; les tableurs abîment les CSV (dates, zéros,
  encodage).

**S2. « Atelier dans la webapp »** : un onglet guidé (lieux, puis sources, puis organisations) dans
la webapp existante, avec fichier de travail téléchargeable et `.gw` corrigé en sortie. LLM par
copier-coller au début.

- Pour : rien à installer, un seul produit à maintenir, déjà hébergé ; touche l'amateur.
- Contre : chantier d'interface conséquent ; sessions courtes à contourner ; pas de LLM intégré.

**S3. « Atelier local »** : application séparée, installable (piste 2 ou 3), avec LLM par clé
personnelle ou Ollama.

- Pour : confidentialité, LLM intégré, pas de limite de session.
- Contre : empaquetage et maintenance multi-système ; l'amateur risque de buter sur l'installation,
  qui était justement l'inquiétude de départ.

Lecture possible (avis, pas décision) : S1 d'abord, car il construit la fondation et sert
l'historien ; S2 ensuite si l'amateur en a besoin ; S3 seulement si la demande d'un LLM intégré se
confirme. Le code actuel de `app/` ne sert directement aucune des trois.

## 7. Fondation commune, quelle que soit la stratégie

1. **Appliquer des corrections à un `.gw`** dans `core` : corrections ciblées, journal des
   changements, `.gw` d'origine jamais modifié, contrôle par `gwc`/`gwu`.
2. **Format du fichier de corrections** (journal) : qui sert à reprendre un travail, à tracer, et à
   recevoir les propositions d'un LLM ou d'un tableur.
3. **Conventions d'écriture** pour lieux, sources, organisations, reconnues par le parser.

## 8. Points ouverts déjà connus (hors atelier, à garder visibles)

- Audit de fidélité : infos en ligne des enfants et témoins, qualificatif avant `+`, convention
  `_`/`\_` (`core/doc/parser_fidelity_audit.md`). À traiter avant d'écrire des `.gw`, au moins pour
  les zones qu'on corrige.
- M6 : recharger un ancien `.org.json` puis ré-inférer duplique les liens.
- Mineurs de l'onglet Organisations et de la webapp (voir les documents de conception).
- `exports_design.md` § 9 : sources multiples, pistes de sources, XML-TEI, rechargement du compagnon.
- Publication de `core` sur PyPI et borne `requires-python`.
- Modifications de documentation du 6 novembre **non commitées** : elles disent « enrichissement par
  LLM abandonné ». À nuancer selon l'issue de cette réflexion (le LLM revient comme aide facultative,
  sans budget de l'auteur).
- Sort du code actuel de `app/` : garder, archiver, ou réutiliser des morceaux.

## 9. Décisions du 7 novembre 2026

Décisions de l'auteur :

- **Public cible : les historiens et les ingénieurs en humanités numériques.** Le généalogiste
  amateur n'est plus visé par l'atelier. L'atelier les fait entrer dans un processus de
  **nettoyage et d'enrichissement du résultat du parser**.
- **Premier thème : les lieux.**
- **LLM : aucun au départ**, puis, au choix de l'utilisateur, copier-coller dans son chatbot, clé
  personnelle ou Ollama.
- **Pas de `.gw` réécrit.** Il n'a aucun intérêt pour ce public : ce que l'utilisateur veut ensuite,
  c'est importer les données nettoyées dans sa propre base de données. L'écrivain `.gw` (§ 5.2,
  § 7.1) est abandonné.
- **Forme : un outil local installé par `uv`**, appuyé sur `geneweb-py`. La webapp Coolify reste la
  vitrine publique, sans LLM.
- **Sorties : toutes les cibles** (SQL générique, outils HN comme Heurist, nodegoat, Omeka S ou
  FactGrid, graphe et web sémantique, XML-TEI), à partir d'un **schéma de données simple, unique**,
  que l'on adapte à chacun de ces outils.
- **Lieux, première version** : regrouper les variantes d'abord ; ensuite, au choix de
  l'utilisateur et cumulables, lier à un référentiel, ajouter coordonnées et hiérarchie, traiter
  l'historicité.
- **Référentiels de lieux : la France d'abord** (COG INSEE et son historique, base Cassini de
  l'EHESS, Wikidata), plus les projets du même type : **SoDUCo, GeoHistoricalData, DicoTopo**,
  entre autres. Les accès (API, téléchargement, licence) restent à vérifier un par un.
- **Interface : une webapp locale** (serveur sur localhost, ouverture du navigateur), qui réutilise la
  pile et les composants de la webapp de `core`.

- **Séparation nette entre `core` et l'atelier, une seule porte d'entrée par fonction.** `core` garde
  l'essentiel : parser, modèle, fonction organisations, tables et zip actuels, webapp vitrine.
  Tout le traitement et l'enrichissement (regroupement des lieux, journal des décisions,
  référentiels, LLM, adaptateurs vers les outils cibles) va dans l'atelier, nouveau membre du
  workspace qui remplace `app/`. Pas de scripts d'atelier dans la CLI de `core`, pour ne pas
  maintenir deux portes d'entrée.

- **Nom provisoire : « Prosopo-gw-Atelier ».** Le nom définitif sera choisi plus tard (pistes :
  Collation, Regeste, Toldot Atelier ; `toldot-collation` libre sur PyPI le 7 novembre).

Proposition associée (non validée) : le pivot de l'atelier part des tables du zip actuel, lues
depuis `core` (`formats/tables.py`), et y ajoute de son côté des **entités** là où il n'y a que du texte (table `lieux`
d'abord, puis sources décomposées et organisations validées) ; chaque valeur enrichie porte son
origine (règle, choix manuel, proposition LLM validée) ; le journal des décisions est rejouable.
Ordre des adaptateurs : SQL/CSV, XML-TEI, RDF/QuickStatements, puis modèles d'import Heurist,
nodegoat, Omeka S.

Conséquences à valider :

- L'obstacle de l'installation (Docker, ligne de commande) tombe en grande partie : la piste 3
  (`uv tool install`) et une application locale redeviennent réalistes, et avec elles la clé
  personnelle et Ollama.
- La sortie n'est plus forcément le seul `.gw` corrigé : un jeu de données propre, traçable et
  réutilisable (CSV, SQLite, JSON, peut-être TEI) peut compter autant que le retour dans GeneWeb.
  Cela change le besoin d'un écrivain `.gw` (§ 7.1).
- Les colonnes « Généalogiste amateur » du § 4 et les pistes 1 et 2 du § 5.5 perdent leur poids.

## 10. Questions pour la reprise

1. La sortie attendue est-elle bien le `.gw` corrigé, avec le journal comme trace ?
2. Par quel thème commencer : lieux, sources ou organisations ?
3. Convention pour les organisations : complément de lieu, tag normalisé, ou autre ?
4. Convention pour les sources : déplacement dans les notes, ou délimiteur et taxinomie ?
5. Stratégie : S1, S2, S3, ou un enchaînement ?
6. LLM : aucun au départ, copier-coller, clé personnelle, local ?
7. Nom de l'atelier.
