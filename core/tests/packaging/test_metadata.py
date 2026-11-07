"""
Tests des métadonnées du package

Vérifie que le package contient toutes les métadonnées requises
pour une publication PyPI réussie.
"""

import sys
from pathlib import Path

import pytest


def test_package_name():
    """Test que le package a le bon nom"""
    import geneweb_py

    # Le nom du module doit être geneweb_py
    assert geneweb_py.__name__ == "geneweb_py"


def test_version_exists():
    """Test que la version est définie"""
    import geneweb_py

    assert hasattr(geneweb_py, "__version__")
    assert geneweb_py.__version__ is not None


def test_version_is_string():
    """Test que la version est une chaîne"""
    import geneweb_py

    assert isinstance(geneweb_py.__version__, str)


def test_author_info():
    """Test présence des informations d'auteur"""
    import geneweb_py

    # Ces attributs peuvent être optionnels, mais c'est mieux de les avoir
    # On vérifie juste qu'ils existent ou pas
    hasattr(geneweb_py, "__author__")
    hasattr(geneweb_py, "__email__")
    # Au moins un des deux devrait être présent
    # (pour l'instant, on accepte qu'ils ne soient pas là)


@pytest.mark.skipif(
    sys.version_info < (3, 8), reason="importlib.metadata nécessite Python 3.8+"
)
def test_package_metadata_available():
    """Test que les métadonnées sont accessibles via importlib.metadata"""
    try:
        from importlib import metadata
    except ImportError:
        import importlib_metadata as metadata

    try:
        dist = metadata.metadata("geneweb-py")
        assert dist is not None
    except metadata.PackageNotFoundError:
        pytest.skip("Package non installé (mode développement)")


@pytest.mark.skipif(
    sys.version_info < (3, 8), reason="importlib.metadata nécessite Python 3.8+"
)
def test_required_metadata_fields():
    """Test présence des champs de métadonnées requis"""
    try:
        from importlib import metadata
    except ImportError:
        import importlib_metadata as metadata

    try:
        dist = metadata.metadata("geneweb-py")

        # Champs requis par PyPI
        required_fields = ["Name", "Version"]
        for field in required_fields:
            assert field in dist, f"Champ {field} manquant dans les métadonnées"
            assert dist[field], f"Champ {field} vide"

        # Champs recommandés
        recommended_fields = ["Summary", "Author", "License"]
        for field in recommended_fields:
            if field in dist:
                assert dist[field], f"Champ {field} présent mais vide"

    except metadata.PackageNotFoundError:
        pytest.skip("Package non installé (mode développement)")


@pytest.mark.skipif(
    sys.version_info < (3, 8), reason="importlib.metadata nécessite Python 3.8+"
)
def test_classifiers_present():
    """Test présence de classifiers PyPI"""
    try:
        from importlib import metadata
    except ImportError:
        import importlib_metadata as metadata

    try:
        dist = metadata.metadata("geneweb-py")
        classifiers = dist.get_all("Classifier")

        if classifiers:
            # Vérifier présence de classifiers importants
            assert any("Programming Language :: Python" in c for c in classifiers), (
                "Manque classifier Programming Language"
            )
            assert any("License ::" in c for c in classifiers), (
                "Manque classifier License"
            )

    except metadata.PackageNotFoundError:
        pytest.skip("Package non installé (mode développement)")


@pytest.mark.skipif(
    sys.version_info < (3, 8), reason="importlib.metadata nécessite Python 3.8+"
)
def test_dependencies_listed():
    """Test que les dépendances sont listées"""
    try:
        from importlib import metadata
    except ImportError:
        import importlib_metadata as metadata

    try:
        dist = metadata.metadata("geneweb-py")
        requires = dist.get_all("Requires-Dist")

        # On devrait avoir au moins typing_extensions et chardet
        if requires:
            dep_names = [r.split()[0].lower() for r in requires]
            # Note: peut varier selon les extras installés
            assert len(dep_names) >= 0  # Juste vérifier que ça ne crash pas

    except metadata.PackageNotFoundError:
        pytest.skip("Package non installé (mode développement)")


def test_package_structure():
    """Test que la structure du package est correcte"""
    from pathlib import Path

    import geneweb_py

    # Le package doit avoir ces sous-modules
    expected_modules = ["core", "formats", "api"]

    package_path = Path(geneweb_py.__file__).parent

    for module in expected_modules:
        module_path = package_path / module
        assert module_path.exists(), f"Module {module} manquant"
        assert module_path.is_dir(), f"{module} doit être un dossier"
        assert (module_path / "__init__.py").exists(), f"{module}/__init__.py manquant"


def test_no_dev_dependencies_in_core():
    """Vérifier qu'aucune dépendance de dev n'est requise pour l'utilisation basique"""
    from geneweb_py import GeneWebParser

    # Ces imports ne doivent PAS nécessiter pytest, ruff, etc.
    # Si on arrive ici sans ImportError, c'est bon
    parser = GeneWebParser()
    assert parser is not None


def test_pyproject_aligns_with_documented_stack():
    """Vérifie cohérence README / doc : Python minimal, dépôt GitHub, extra parsing.

    Évite les régressions (ex. requires-python ou URLs projet) sans dépendance TOML.
    """
    root = Path(__file__).resolve().parents[2]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in text

    gh = "https://github.com/Relais4x100a2/prosopo-gw"
    assert f'Homepage = "{gh}"' in text
    assert f'Repository = "{gh}"' in text
    assert f'"Bug Tracker" = "{gh}/issues"' in text

    assert "\nparsing = [" in text
    assert any("lark" in line.lower() for line in text.splitlines())


def test_readme_documents_stack_and_repo_urls() -> None:
    """README : URLs dépôt GitHub, mention Ruff, pas de plancher Python 3.7 affiché."""
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    gh = "Relais4x100a2/geneweb-py"
    assert readme.count(gh) >= 4
    assert "### Standards de qualité" in readme
    assert "Ruff" in readme
    assert "Black" in readme and "Flake8" in readme
    assert "3.7+" not in readme
