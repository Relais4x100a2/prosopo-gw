# geneweb-py

[![Python](https://img.shields.io/pypi/pyversions/geneweb-py?logo=python&label=Python&color=blue)](https://github.com/Relais4x100a2/geneweb-py/blob/main/pyproject.toml)
[![PyPI version](https://img.shields.io/badge/pypi-v0.1.0-blue.svg)](https://pypi.org/project/geneweb-py/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://github.com/Relais4x100a2/prosopo-gw/actions/workflows/ci.yml/badge.svg)](https://github.com/Relais4x100a2/prosopo-gw/actions/workflows/ci.yml)

Librairie Python complète pour parser, manipuler et convertir les fichiers généalogiques au format GeneWeb (.gw).

## 🚀 Fonctionnalités

- **Parser complet** : Lecture et parsing des fichiers .gw avec support gwplus ✅
- **Parser avancé** : Support des apostrophes, caractères spéciaux, numéros d'occurrence ✅
- **Nouveaux blocs** : Support complet des blocs `notes-db`, `page-ext`, `wizard-note` ✅
- **Modèles de données** : Représentation structurée des personnes, familles et événements ✅
- **API REST moderne** : FastAPI avec endpoints complets pour CRUD ✅
- **Validation** : Vérification de cohérence des données généalogiques ✅
- **Messages d'erreur enrichis** : Erreurs contextuelles avec numéro de ligne, tokens, et suggestions ✅
- **Validation gracieuse** : Mode strict/gracieux pour collecter toutes les erreurs ou s'arrêter à la première ✅
- **Conversion** : Export/import vers GEDCOM, JSON, XML et autres formats ✅
- **CLI** : commande `geneweb-py` (parse / export) avec l’extra `[cli]` ✅
- **Performance** : Optimisations avancées (streaming, cache LRU, __slots__) ✅
  - Mode streaming automatique pour gros fichiers (>10MB)
  - Réduction mémoire de ~80% sur fichiers volumineux
  - Optimisations CPU : ~15-20% plus rapide sur petits fichiers
  - Parser **multi-passes** (`use_multipass=True`) pour renforcer la résolution des références croisées sur des bases complexes

### Quand utiliser le streaming vs le mode multi-passes ?

| Besoin | Réglage recommandé |
|--------|-------------------|
| Fichier très volumineux, limiter la **mémoire** (lexique + tokens en flux) | Laisser le seuil par défaut ou forcer `stream_mode=True` sur `GeneWebParser` ; le streaming s’active automatiquement au-delà du seuil (10 Mo par défaut). |
| Fichier chargé en mémoire (taille modeste à grande) avec **beaucoup de références croisées** (familles, témoins, blocs dispersés) | `GeneWebParser(use_multipass=True)` : une passe supplémentaire met à jour les liens personnes ↔ familles après fusion de toutes les personnes. |
| Très gros fichier **et** références difficiles | `stream_mode=True` **et** `use_multipass=True` : le pipeline streaming produit les mêmes nœuds syntaxiques, puis la phase multi-passes reconstruit les modèles avec la passe de références renforcée. |

Le streaming agit sur la **lecture et la tokenisation** ; le multi-passes agit sur la **construction du graphe généalogique**. Ils ne s’excluent pas.

## 📦 Installation

```bash
pip install geneweb-py
```

**→ [Démarrage rapide après `pip install`](QUICK_START_PYPI.md)** : parsing, export GEDCOM/JSON, lancement de l’API en quelques minutes.

### Ligne de commande (`geneweb-py`)

Avec l’extra **`cli`** (Click + Rich) :

```bash
pip install "geneweb-py[cli]"
geneweb-py --help
geneweb-py parse ma_base.gw
geneweb-py export ma_base.gw --format gedcom -o sortie.ged
geneweb-py export ma_base.gw --format json -o sortie.json
geneweb-py export ma_base.gw --format xml -o sortie.xml
```

Les erreurs de parsing ou d’export sont affichées sur la sortie d’erreur avec des panneaux Rich.

Pour le développement :

```bash
pip install geneweb-py[dev]
```

Extras disponibles (voir `[project.optional-dependencies]` dans `pyproject.toml`) : `dev`, `docs`, `cli`, `validation`, `api`. L’extra optionnel **`parsing`** installe [Lark](https://github.com/lark-parser/lark) pour d’éventuels travaux sur une grammaire déclarative ; **le parser GeneWeb actuel n’en dépend pas** — réservé à un usage expérimental ou futur (non requis pour parser des fichiers `.gw`).

## 🎯 Utilisation rapide

### Parser un fichier .gw

```python
from geneweb_py import GeneWebParser

# Créer le parser
parser = GeneWebParser()

# Parser un fichier
genealogy = parser.parse_file("ma_famille.gw")

# Afficher des statistiques
print(f"Nombre de personnes : {len(genealogy.persons)}")
print(f"Nombre de familles : {len(genealogy.families)}")
```

### API REST avec FastAPI

```python
# Démarrer l'API
from geneweb_py.api import app
import uvicorn

uvicorn.run(app, host="0.0.0.0", port=8000)

# L'API sera disponible sur http://localhost:8000/docs
```

**CORS (déploiement)** : définir `GENEWEB_API_ENV=prod` (ou lancer `python run_api.py --env prod`, qui positionne cette variable avant le chargement de l’app) et lister les origines autorisées dans `ALLOWED_ORIGINS` (URLs séparées par des virgules, ex. `https://app.example.com,https://admin.example.com`). En production, tant que ni `ALLOWED_ORIGINS` ni `CORS_ORIGINS` ne sont définies, aucune origine cross-origin n’est autorisée par défaut. La variable `CORS_ORIGINS` reste prise en charge pour compatibilité, mais `ALLOWED_ORIGINS` est prioritaire.

### Rechercher une personne

```python
# Rechercher par nom
person = genealogy.find_person("CORNO", "Joseph")

if person:
    print(f"Nom : {person.full_name}")
    print(f"Naissance : {person.birth_date}")
    print(f"Décès : {person.death_date}")
    
    # Obtenir les familles
    families = person.get_families()
    for family in families:
        print(f"Époux(se) : {family.spouse(person)}")
```

### Utiliser l'API REST

```python
# Via l'API REST
import requests

# Lister les personnes
response = requests.get("http://localhost:8000/api/v1/persons")
print(f"Personnes : {response.json()}")

# Obtenir une personne
person = requests.get("http://localhost:8000/api/v1/persons/1")
print(f"Personne : {person.json()}")
```

### Nouvelles fonctionnalités du parser

```python
# Démontrer les améliorations récentes
python examples/parser_improvements_demo.py

# Exemple de parsing avec apostrophes et caractères spéciaux
content = """
fam d'Arc Jean-Marie .1 #occu Ingénieur_(ENSIA),_Aumônier_de_l'enseignement + O'Brien Marie-Claire .2
wit m: LEROY Bernard .1 #occu Dominicain,_Aumônier_de_l'enseignement_technique_à_Rouen
beg
- h Pierre_Bernard .1 #occu Ingénieur,_éditeur
- f Marie_Claire .2 #occu Conseillère_en_économie_sociale_et_familiale
end

notes-db
Notes générales sur cette famille
end notes-db

page-ext d'Arc Jean-Marie .1
<h1>Page de Jean-Marie d'Arc</h1>
end page-ext

wizard-note O'Brien Marie-Claire .2
Note générée par le wizard pour Marie-Claire
end wizard-note
"""

parser = GeneWebParser()
genealogy = parser.parse_string(content)

# Toutes les personnes sont correctement parsées avec leurs occupations
for person in genealogy.persons.values():
    print(f"{person.first_name} {person.last_name} - {person.occupation}")
```

### Validation gracieuse et gestion d'erreurs

Le parser supporte deux modes de gestion d'erreurs :

#### Mode strict (par défaut) - S'arrête à la première erreur

```python
from geneweb_py import GeneWebParser

parser = GeneWebParser(strict=True)  # Mode par défaut
try:
    genealogy = parser.parse_file("fichier_avec_erreur.gw")
except GeneWebParseError as e:
    print(f"Erreur de parsing : {e}")
    # Message enrichi avec ligne, token attendu, contexte
```

#### Mode gracieux - Collecte toutes les erreurs

```python
from geneweb_py import GeneWebParser

# Mode gracieux : continue le parsing malgré les erreurs
parser = GeneWebParser(strict=False, validate=True)
genealogy = parser.parse_file("fichier_avec_erreurs.gw")

# Vérifier si la généalogie est valide
if not genealogy.is_valid:
    print(f"Erreurs détectées : {len(genealogy.validation_errors)}")
    
    # Obtenir un résumé
    print(genealogy.get_validation_summary())
    
    # Afficher toutes les erreurs
    for error in genealogy.validation_errors:
        print(f"- {error}")  # Messages enrichis avec contexte

# Rapport détaillé des erreurs
if parser.error_collector.has_errors():
    print(parser.error_collector.get_detailed_report())
```

#### Messages d'erreur enrichis

Les erreurs incluent automatiquement :
- Numéro de ligne
- Token trouvé vs token attendu
- Contexte (quelle personne, famille, etc.)
- Sévérité (WARNING, ERROR, CRITICAL)

```python
# Exemple de message d'erreur enrichi :
# Ligne 42: Token inattendu
#   Token trouvé: 'invalid'
#   Attendu: fam, nom, ou date
#   Contexte: Parsing d'une personne
```

#### Validation des données

```python
from geneweb_py.core.validation import (
    validate_person_basic,
    validate_family_basic,
    validate_genealogy_consistency
)

# Valider une personne
result = validate_person_basic(person)
if not result.is_valid():
    print(f"Erreurs : {result.get_error_messages()}")
    print(f"Avertissements : {result.get_warning_messages()}")

# Valider toute la généalogie
result = validate_genealogy_consistency(genealogy)
print(result.get_summary())  # Résumé des erreurs et avertissements
```

### Conversion de formats

```python
from geneweb_py.formats import GEDCOMExporter, JSONExporter, XMLExporter

# Export vers GEDCOM
gedcom_exporter = GEDCOMExporter()
gedcom_exporter.export(genealogy, "ma_famille.ged")

# Export vers JSON
json_exporter = JSONExporter()
json_exporter.export(genealogy, "ma_famille.json")

# Export vers XML
xml_exporter = XMLExporter()
xml_exporter.export(genealogy, "ma_famille.xml")

# Import depuis JSON
from geneweb_py.formats import JSONImporter
json_importer = JSONImporter()
imported_genealogy = json_importer.import_from_file("ma_famille.json")
```

## ⚡ Optimisations de performance

geneweb-py inclut des optimisations avancées pour gérer efficacement les fichiers volumineux :

```python
from geneweb_py.core.parser.gw_parser import GeneWebParser

# Mode automatique : détecte la taille et choisit le meilleur mode
parser = GeneWebParser()
genealogy = parser.parse_file("gros_fichier.gw")  # Streaming si >10MB

# Estimer l'utilisation mémoire avant parsing
estimate = parser.get_memory_estimate("gros_fichier.gw")
print(f"Mémoire estimée : {estimate['estimated_streaming_memory_mb']} MB")
print(f"Économie : {estimate['memory_saving_percent']}%")

# Mode streaming forcé pour économiser la mémoire
parser = GeneWebParser(stream_mode=True)

# Désactiver la validation pour plus de vitesse
parser = GeneWebParser(validate=False)
```

**Gains mesurés** :
- Fichiers >10MB : ~80% de réduction mémoire avec le streaming
- Petits fichiers : ~15-20% plus rapide grâce aux optimisations CPU
- Exemple : fichier 50MB passe de ~375MB RAM à ~75MB RAM

**Voir aussi** :
- [Guide complet des performances](doc/PERFORMANCE.md)
- [Exemple de démonstration](examples/performance_demo.py)
- [Benchmarks](tests/performance/benchmark_parser.py)

## 📚 Documentation

**→ [Guide complet de la documentation](DOCUMENTATION.md)** - Index central et parcours recommandés

### Essentiel
- **[README.md](README.md)** - 👈 Vous êtes ici - Guide d'utilisation
- **[CHANGELOG.md](CHANGELOG.md)** - Historique des versions
- **[doc/status.md](doc/status.md)** - État du projet et métriques
- **[doc/roadmap.md](doc/roadmap.md)** - Vision à long terme

### Guides spécialisés
- **[doc/PERFORMANCE.md](doc/PERFORMANCE.md)** ⚡ - Optimisations et benchmarks
- **[QUICK_START_PYPI.md](QUICK_START_PYPI.md)** 📦 - Démarrage rapide (install PyPI)
- **[doc/geneweb/gw_format_documentation.md](doc/geneweb/gw_format_documentation.md)** - Format .gw

### Ressources
- **[examples/](examples/)** - Scripts de démonstration
- **[tests/](tests/)** - Suite de tests (volume à jour dans [doc/status.md](doc/status.md))
- **[Documentation API](http://localhost:8000/docs)** - Swagger UI (API REST)
- **[GeneWeb Community](https://web.archive.org/web/20250802144922/https://geneweb.tuxfamily.org/wiki/GeneWeb)** - Documentation communautaire

## 🧪 Tests

geneweb-py dispose d'une suite de tests **consolidée et organisée**. Les comptages exacts et l’instantané de couverture documenté sont tenus à jour dans **[doc/status.md](doc/status.md)** ; la tendance sur `main` est visible sur **[Codecov](https://codecov.io/gh/Relais4x100a2/geneweb-py)** (CI). En local : `python3 -m pytest tests/ --cov=src/geneweb_py` (extras `dev`, `api`, `validation`).

### 📁 Structure des Tests

```
tests/
├── unit/                    # Tests unitaires par module (18 fichiers)
│   ├── test_date.py         # Tests pour core.date
│   ├── test_event.py        # Tests pour core.event  
│   ├── test_person.py       # Tests pour core.person
│   ├── test_family.py       # Tests pour core.family
│   ├── test_exceptions.py   # Tests pour core.exceptions
│   ├── test_validation.py   # Tests pour core.validation
│   ├── test_parser*.py      # Tests pour core.parser
│   └── test_formats*.py     # Tests pour formats.*
├── integration/             # Tests d'intégration
├── compatibility/           # Tests de compatibilité Python
├── packaging/              # Tests de packaging PyPI
└── security/               # Tests de sécurité
```

### 🚀 Exécution des Tests

```bash
# Exécuter tous les tests
pytest

# Tests unitaires seulement (recommandé pour le développement)
pytest tests/unit/

# Tests avec couverture
pytest --cov=geneweb_py --cov-report=html

# Tests sans les tests lents
pytest -m "not slow"

# Tests d'intégration seulement
pytest tests/integration/

# Tests de packaging (PyPI)
pytest tests/packaging/

# Tests de compatibilité multi-versions
pytest tests/compatibility/

# Tests de sécurité
pytest tests/security/

# Voir les tests skippés et leurs raisons
pytest -rs
```

### 📊 Métriques de Qualité

- **Tests et couverture** : voir **[doc/status.md](doc/status.md)** (instantané versionné) et le badge **Codecov** en tête de ce README.
- **Modules critiques** : parser, validation et exceptions sont en majorité très couverts ; le détail par fichier est dans le rapport `htmlcov/` après `pytest --cov`.
- **Temps d'exécution** : de l’ordre de quelques secondes pour la suite complète sur machine récente

### 🔧 Configuration des Tests

Les tests sont configurés dans `pyproject.toml` avec :
- **Couverture minimale** : 80%
- **Marqueurs** : `slow`, `integration`, `unit`, `coverage`, `parser`, `validation`, `formats`
- **Filtres d'avertissements** : Déprecations ignorées
- **Traceback court** : Pour des rapports concis

### 📝 Documentation des Tests

- **[Structure des tests](tests/README.md)** : Organisation et bonnes pratiques
- **[Tests skippés](tests/SKIPPED_TESTS.md)** : Documentation des tests temporairement désactivés
- **Couverture** : Rapport HTML généré dans `htmlcov/`

## 🚀 Développement et Publication

### Installation en mode développement

```bash
git clone https://github.com/Relais4x100a2/geneweb-py.git
cd geneweb-py
pip install -e .[dev]
```

### Validation avant publication PyPI

geneweb-py inclut des scripts de validation pour garantir la qualité avant publication :

```bash
# Validation complète (bash)
./scripts/validate_pypi.sh

# Vérification avancée (Python)
python scripts/check_pypi_readiness.py

# Construction du package
python -m build

# Vérification avec twine
twine check dist/*

# Tests de packaging
pytest tests/packaging/ -v
```

### Publication sur PyPI

```bash
# 1. Publication sur TestPyPI (pour tester)
twine upload --repository testpypi dist/*

# 2. Test d'installation depuis TestPyPI
pip install --index-url https://test.pypi.org/simple/ geneweb-py

# 3. Publication sur PyPI (production)
twine upload dist/*
```

**Note** : La publication est automatisée via GitHub Actions. Voir `.github/workflows/test-pypi.yml`

### Compatibilité

geneweb-py est testé et compatible avec :
- **Python** : 3.8, 3.9, 3.10, 3.11, 3.12 (voir `requires-python` dans `pyproject.toml`)
- **OS** : Linux, macOS, Windows
- **Architectures** : x86_64, arm64

## 🤝 Contribution

Les contributions sont les bienvenues ! Consultez le [Statut du projet](doc/status.md) et la [Roadmap](doc/roadmap.md) pour comprendre la direction actuelle et proposer des améliorations.

### Processus de contribution

1. Fork le projet
2. Créer une branche (`git checkout -b feature/AmazingFeature`)
3. Commit les changements (`git commit -m 'Add AmazingFeature'`)
4. Push vers la branche (`git push origin feature/AmazingFeature`)
5. Ouvrir une Pull Request

### Standards de qualité

Le projet n’utilise **ni Black ni Flake8** : le formatage, le lint et le tri des imports sont assurés par **Ruff** (`ruff format`, `ruff check`, configuration dans `[tool.ruff]` de `pyproject.toml`), en remplacement de l’écosystème Black + Flake8 + isort.

- Tests unitaires obligatoires (couverture ≥ 90% sur les modules critiques)
- Annotations de type sur toutes les fonctions publiques
- Docstrings en français (style Google)
- **Ruff** pour le formatage et le lint — aligné sur `pyproject.toml` ; commandes locales : `ruff format .` puis `ruff check .`
- Vérification des types avec **mypy** (mode strict)
- **Sécurité des dépendances** : le workflow [.github/workflows/security.yml](.github/workflows/security.yml) exécute **pip-audit** sur les extras `api`, `validation` et `parsing` (cœur + optionnels « runtime » documentés) à chaque PR et chaque semaine ; pour un contrôle local, installer l’extra `dev` puis lancer `pip-audit` selon vos besoins

## 📄 Licence

Ce projet est sous licence MIT. Voir [LICENSE](LICENSE) pour plus de détails.

## 🔗 Liens utiles

- [GeneWeb GitHub repo](http://geneweb.org/)
- [Format .gw](doc/geneweb/gw_format_documentation.md)
- [Geneweb documentation by the community](https://web.archive.org/web/20250802144922/https://geneweb.tuxfamily.org/wiki/GeneWeb)
- [Issues](https://github.com/Relais4x100a2/geneweb-py/issues)
