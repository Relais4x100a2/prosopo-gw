import io
import json
import shutil
import sqlite3
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from prosopo_gw_atelier.export.archive import build_archive
from prosopo_gw_atelier.project import Project
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store.registry import PlaceRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GENERATED_AT = datetime(2026, 11, 7, 14, 30, 12)


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "data" / "referentiel.sqlite") as reg:
        yield reg


@pytest.fixture
def project(tmp_path: Path, registry: PlaceRegistry, ref: RefData) -> Project:
    gw = tmp_path / "bases" / "lieux_varies.gw"
    gw.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "lieux_varies.gw", gw)
    return Project.open(gw, registry, ref, tmp_path / "data" / "projects")


@pytest.fixture
def lyon(registry: PlaceRegistry) -> str:
    return registry.validate(
        ["Lyon"],
        {"commune": "Lyon", "insee_code": "69123"},
        {"commune": "rule", "insee_code": "rule"},
        project="p",
    )


def open_zip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def test_exact_file_list(
    project: Project, registry: PlaceRegistry, ref: RefData
) -> None:
    names = open_zip(build_archive(project, registry, ref, GENERATED_AT)).namelist()
    assert names == [
        "LISEZMOI.txt",
        "dictionnaire.csv",
        "personnes.csv",
        "familles.csv",
        "enfants.csv",
        "evenements.csv",
        "temoins.csv",
        "sources.csv",
        "lieux.csv",
        "ecritures_lieux.csv",
        "lieux_varies.json",
        "lieux_varies.sqlite",
    ]
    assert not [n for n in names if n.endswith(".org.json")]


def test_readme(project: Project, registry: PlaceRegistry, ref: RefData) -> None:
    archive = open_zip(build_archive(project, registry, ref, GENERATED_AT))
    readme = archive.read("LISEZMOI.txt").decode("utf-8")
    assert ref.cog_vintage and ref.postal_vintage
    assert f"millésime {ref.cog_vintage}" in readme
    assert f"millésime {ref.postal_vintage}" in readme
    assert "Licence Ouverte 2.0" in readme
    assert "lieux_varies.gw" in readme
    assert "2026-11-07" in readme
    assert "personnes vivantes" in readme
    assert "rule" in readme and "manual" in readme
    assert "{" not in readme


def test_contents(
    project: Project, registry: PlaceRegistry, ref: RefData, lyon: str
) -> None:
    archive = open_zip(build_archive(project, registry, ref, GENERATED_AT))
    payload = json.loads(archive.read("lieux_varies.json"))
    assert payload["base"] == "lieux_varies"
    assert payload["generated_at"] == "2026-11-07T14:30:12"
    assert [r["lieu_id"] for r in payload["tables"]["lieux"]] == [lyon]
    occu = next(
        r
        for r in payload["tables"]["evenements"]
        if r["evenement_id"] == "pevt:DUPONT_Jean_0:2"
    )
    assert (occu["lieu_id"], occu["complement"]) == (lyon, "Atelier Rose")

    dictionary = archive.read("dictionnaire.csv").decode("utf-8")
    assert "\nlieux;commune_origine;texte;" in dictionary
    assert "\npersonnes;naissance_lieu_id;texte;" in dictionary

    places_csv = archive.read("lieux.csv").decode("utf-8")
    assert lyon in places_csv

    db = Path(project.state_path).parent / "export.sqlite"
    db.write_bytes(archive.read("lieux_varies.sqlite"))
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT lieu_id, commune FROM lieux").fetchall()
        writings = conn.execute(
            "SELECT ecriture, statut FROM ecritures_lieux"
        ).fetchall()
    assert rows == [(lyon, "Lyon")]
    assert writings == [("Lyon", "validated")]


def test_deterministic(
    project: Project, registry: PlaceRegistry, ref: RefData, lyon: str
) -> None:
    first = build_archive(project, registry, ref, GENERATED_AT)
    second = build_archive(project, registry, ref, GENERATED_AT)
    assert first == second
    for info in open_zip(first).infolist():
        assert info.date_time == (2026, 11, 7, 14, 30, 12)
    assert build_archive(project, registry, ref, datetime(2026, 11, 8)) != first
