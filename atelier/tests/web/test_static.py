"""The browser page and its static files (design § 7), and their packaging."""

import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prosopo_gw_atelier.project import Project
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store.registry import PlaceRegistry
from prosopo_gw_atelier.web.app import create_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ATELIER = Path(__file__).resolve().parents[2]
STATIC = "prosopo_gw_atelier/web/static"
VENDOR = (
    "bootstrap.bundle.min.js",
    "bootstrap.min.css",
    "tabulator.min.css",
    "tabulator.min.js",
    "LICENSES.txt",
)


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


@pytest.fixture
def client(tmp_path: Path, ref: RefData) -> Iterator[TestClient]:
    gw = tmp_path / "bases" / "lieux_varies.gw"
    gw.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "lieux_varies.gw", gw)
    with PlaceRegistry(tmp_path / "data" / "referentiel.sqlite") as registry:
        project = Project.open(gw, registry, ref, tmp_path / "data" / "projets")
        yield TestClient(
            create_app(project, registry, ref), base_url="http://127.0.0.1"
        )


def test_index_serves_the_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert '<html lang="fr">' in page
    assert "/static/app.js" in page
    assert "/static/style.css" in page


@pytest.mark.parametrize(
    "path", ["app.js", "style.css", *(f"vendor/{name}" for name in VENDOR)]
)
def test_static_files_are_served(client: TestClient, path: str) -> None:
    response = client.get(f"/static/{path}")
    assert response.status_code == 200
    assert response.content


def test_page_links_the_exports_and_the_registry(client: TestClient) -> None:
    page = client.get("/").text
    assert 'href="/api/export"' in page
    assert 'id="registry-button"' in page
    assert 'id="registry"' in page
    script = client.get("/static/app.js").text
    for route in (
        "/api/registry/export",
        "/api/registry/import",
        "/api/registry/conflicts",
        "/api/registry/conflicts/resolve",
        "/api/registry/journal",
    ):
        assert route in script


def test_sources_tab_present(client: TestClient) -> None:
    page = client.get("/").text
    assert 'id="sources-button"' in page
    assert 'id="sources"' in page
    script = client.get("/static/app.js").text
    for text in (
        "Sources",
        "Télécharger",
        "CC BY-NC-ND",
        "/api/sources",
        "Relancer les échecs",
        "/api/source-proposals/refuse",
        "source-proposals/accept",
    ):
        assert text in script


def test_script_never_assigns_inner_html(client: TestClient) -> None:
    """Place names come from user files: the page builds nodes, never HTML."""
    script = client.get("/static/app.js").text
    assert "innerHTML" not in script
    assert "outerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "encodeURIComponent" in script


def test_wheel_ships_static_files(tmp_path: Path) -> None:
    """Build a wheel from a copy of the package, so the repository stays clean."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    source = tmp_path / "src-copy"
    source.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copyfile(ATELIER / name, source / name)
    shutil.copytree(
        ATELIER / "src",
        source / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    dist = tmp_path / "dist"
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist), str(source)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    (wheel,) = dist.glob("prosopo_gw_atelier-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert f"{STATIC}/index.html" in names
    assert f"{STATIC}/app.js" in names
    assert f"{STATIC}/style.css" in names
    for name in VENDOR:
        assert f"{STATIC}/vendor/{name}" in names


def test_index_forbids_inline_and_remote_scripts(client: TestClient) -> None:
    policy = client.get("/").headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/static/style.css"])
def test_page_files_are_revalidated(client: TestClient, path: str) -> None:
    assert client.get(path).headers["cache-control"] == "no-cache"


def test_script_edits_level_chains(client: TestClient) -> None:
    """The validation screen edits place level chains, not fixed fields."""
    script = client.get("/static/app.js").text
    for needle in (
        "/levels",
        "accept",
        "refuse",
        "Retenir cette lecture",
        "Ajouter un niveau",
        "level_types",
        "Commune historique",
    ):
        assert needle in script
    for gone in ("former_name", "Ancien nom", "detail.proposal", "detail.origins"):
        assert gone not in script


def test_precisions_tab_present(client: TestClient) -> None:
    page = client.get("/").text
    script = client.get("/static/app.js").text
    assert 'id="precisions-button"' in page
    assert "Précisions" in page + script
    assert "Aucun arrondissement" in script
    assert "numéro écrit" in script
    assert "/api/precisions/decide" in script
    assert "aucun (n'existait pas à cette date)" in script
    assert "/api/precisions/clear" in script
    assert "Revenir au calcul" in script
    assert "aucun arrondissement (choix manuel)" in script
