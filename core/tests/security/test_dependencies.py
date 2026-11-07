"""
Tests de sécurité des dépendances

Vérifie que les dépendances n'ont pas de vulnérabilités connues
et que les versions sont appropriées.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.security


def _repo_root() -> Path:
    """Retourne la racine du dépôt (répertoire contenant ``pyproject.toml``).

    Raises:
        RuntimeError: Si aucun ``pyproject.toml`` n'est trouvé en remontant depuis
            ce fichier de test.

    Returns:
        Chemin absolu vers la racine du dépôt.
    """
    test_file = Path(__file__).resolve()
    for parent in test_file.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError(
        f"Racine du dépôt introuvable (aucun pyproject.toml parent de {test_file})."
    )


def _package_source_root() -> Path:
    """Racine du code source du package ``geneweb_py`` sous ``src/``.

    Cible ``src/geneweb_py`` (layout src) et non un dossier ``geneweb_py``
    à la racine du clone.

    Raises:
        FileNotFoundError: Si ``src/geneweb_py`` n'existe pas.

    Returns:
        Chemin absolu vers ``src/geneweb_py``.
    """
    root = _repo_root()
    package_root = root / "src" / "geneweb_py"
    if not package_root.is_dir():
        raise FileNotFoundError(
            f"Package source attendu introuvable: {package_root} (layout standard: "
            "src/geneweb_py/)."
        )
    return package_root


def test_security_scans_use_src_package_layout():
    """Garantit que l'analyse statique cible ``src/geneweb_py``.

    Pas un package cloné à la racine du dépôt : les chemins du type
    ``/workspace/geneweb_py`` (hors ``src/``) ne doivent pas être utilisés après
    migration vers un layout PEP 517 ``src``.
    """
    root = _repo_root()
    expected = root.joinpath("src", "geneweb_py").resolve()
    assert _package_source_root().resolve() == expected
    assert expected.is_dir()
    assert (expected / "__init__.py").is_file()


def test_minimal_dependencies():
    """Vérifier qu'on n'a pas trop de dépendances obligatoires"""
    # Lire pyproject.toml
    pyproject_path = _repo_root() / "pyproject.toml"

    if not pyproject_path.exists():
        pytest.skip("pyproject.toml non trouvé")

    with open(pyproject_path) as f:
        content = f.read()

    # Compter les dépendances dans la section dependencies
    # (parsing simple, pas de toml parser pour éviter une dépendance)
    in_deps_section = False
    dep_count = 0

    for line in content.split("\n"):
        if line.strip() == "dependencies = [":
            in_deps_section = True
        elif in_deps_section and "]" in line:
            break
        elif in_deps_section and '"' in line:
            dep_count += 1

    # Maximum 10 dépendances obligatoires pour une lib
    assert dep_count <= 10, (
        f"Trop de dépendances obligatoires ({dep_count}), limite: 10"
    )


def test_dependencies_have_versions():
    """Vérifier que les dépendances ont des contraintes de version"""
    pyproject_path = _repo_root() / "pyproject.toml"

    if not pyproject_path.exists():
        pytest.skip("pyproject.toml non trouvé")

    with open(pyproject_path) as f:
        content = f.read()

    # Vérifier que chaque dépendance a >=, ==, ~= ou autre
    in_deps_section = False

    for line in content.split("\n"):
        if line.strip() == "dependencies = [":
            in_deps_section = True
        elif in_deps_section and "]" in line:
            break
        elif in_deps_section and '"' in line:
            # Extraire le nom de la dépendance
            dep = line.strip().strip('",')
            if dep:
                # Doit contenir un opérateur de version
                has_version = any(
                    op in dep for op in [">=", "==", "~=", ">", "<", "!="]
                )
                assert has_version, f"Dépendance {dep} sans contrainte de version"


def test_dependencies_licenses_compatible():
    """Vérifier que les licences des dépendances sont compatibles avec MIT"""
    # typing_extensions: PSF (compatible)
    # chardet: LGPL (compatible avec MIT pour usage)

    # Licences incompatibles avec MIT pour distribution

    # Pour l'instant, test simple : vérifier qu'on n'a pas de dépendances GPL
    # (nécessiterait pip-licenses pour un test complet)
    pyproject_path = _repo_root() / "pyproject.toml"

    if not pyproject_path.exists():
        pytest.skip("pyproject.toml non trouvé")

    with open(pyproject_path) as f:
        content = f.read()

    # Les packages GPL connus
    gpl_packages = ["gpl", "gnuplot"]  # Liste indicative

    for pkg in gpl_packages:
        assert pkg not in content.lower(), f"Dépendance GPL potentielle détectée: {pkg}"


def test_no_test_dependencies_in_main():
    """Vérifier qu'aucune dépendance de test n'est dans dependencies"""
    pyproject_path = _repo_root() / "pyproject.toml"

    if not pyproject_path.exists():
        pytest.skip("pyproject.toml non trouvé")

    with open(pyproject_path) as f:
        content = f.read()

    # Packages qui doivent être uniquement dans [dev]
    test_packages = ["pytest", "ruff", "black", "flake8", "mypy", "coverage"]

    # Parser les sections
    lines = content.split("\n")
    in_main_deps = False
    main_deps_content = []

    for line in lines:
        if line.strip() == "dependencies = [":
            in_main_deps = True
        elif in_main_deps and "]" in line:
            in_main_deps = False
        elif in_main_deps:
            main_deps_content.append(line.lower())

    main_deps_str = "\n".join(main_deps_content)

    for pkg in test_packages:
        assert pkg not in main_deps_str, (
            f"Package de test {pkg} trouvé dans dependencies principales"
        )


def test_secure_imports():
    """Vérifier qu'on n'importe pas de modules dangereux"""
    import ast

    # Modules potentiellement dangereux (import / from … import)
    dangerous_modules: set[str] = {"pickle", "shelve", "marshal"}

    package_root = _package_source_root()
    py_files = list(package_root.rglob("*.py"))

    assert py_files, f"Aucun fichier .py sous {package_root}"

    for py_file in py_files:
        with open(py_file, encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=str(py_file))
            except SyntaxError:
                # Ignorer les erreurs de syntaxe (fichiers templates, etc.)
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".", 1)[0]
                        assert top not in dangerous_modules, (
                            f"Import dangereux {alias.name!r} dans {py_file}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module is None:
                        continue
                    top = node.module.split(".", 1)[0]
                    assert top not in dangerous_modules, (
                        f"Import dangereux depuis {node.module!r} dans {py_file}"
                    )
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        assert node.func.id not in {"eval", "exec"}, (
                            f"Appel à {node.func.id!r} dans {py_file}"
                        )
                    elif isinstance(node.func, ast.Attribute):
                        assert node.func.attr not in {"eval", "exec"}, (
                            f"Appel à {node.func.attr!r} dans {py_file}"
                        )


def test_no_hardcoded_secrets():
    """Vérifier absence de secrets hardcodés"""
    import re

    # Patterns de secrets communs
    secret_patterns = [
        r'api[_-]?key\s*=\s*["\'][a-zA-Z0-9]{20,}["\']',
        r'password\s*=\s*["\'].+["\']',
        r'secret\s*=\s*["\'].+["\']',
        r'token\s*=\s*["\'][a-zA-Z0-9]{20,}["\']',
    ]

    package_root = _package_source_root()
    py_files = list(package_root.rglob("*.py"))

    assert py_files, f"Aucun fichier .py sous {package_root}"

    for py_file in py_files:
        with open(py_file, encoding="utf-8") as f:
            content = f.read()

            for pattern in secret_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                # Exclure les valeurs de test évidentes
                real_matches = [
                    m
                    for m in matches
                    if "test" not in m.lower()
                    and "example" not in m.lower()
                    and "dummy" not in m.lower()
                ]

                if real_matches:
                    pytest.fail(f"Secret potentiel trouvé dans {py_file}: {matches[0]}")
