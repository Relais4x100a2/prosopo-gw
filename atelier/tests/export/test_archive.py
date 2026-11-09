import io
import json
import shutil
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from prosopo_gw_atelier.export.archive import build_archive
from prosopo_gw_atelier.places.levels import Level
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
        [Level(0, "Lyon", type="commune", identifier="69123", origin="rule")],
        None,
        None,
        project="p",
    ).place_id


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
        "niveaux_lieux.csv",
        "precisions_occurrences.csv",
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
    assert "regle" in readme and "manuel" in readme and "insee" in readme
    assert "rejete" in readme and "valide" in readme
    assert "{" not in readme


def test_readme_mentions_levels(
    project: Project, registry: PlaceRegistry, ref: RefData
) -> None:
    archive = open_zip(build_archive(project, registry, ref, GENERATED_AT))
    readme = archive.read("LISEZMOI.txt").decode("utf-8")
    assert "niveaux_lieux" in readme
    assert "ecrit" in readme


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
    assert writings == [("Lyon", "valide")]


def test_deterministic(
    project: Project, registry: PlaceRegistry, ref: RefData, lyon: str
) -> None:
    first = build_archive(project, registry, ref, GENERATED_AT)
    second = build_archive(project, registry, ref, GENERATED_AT)
    assert first == second
    for info in open_zip(first).infolist():
        assert info.date_time == (2026, 11, 7, 14, 30, 12)
    assert build_archive(project, registry, ref, datetime(2026, 11, 8)) != first


def test_deterministic_with_an_odd_second(
    project: Project, registry: PlaceRegistry, ref: RefData, lyon: str
) -> None:
    odd = datetime(2026, 11, 7, 14, 30, 13)  # zip times have a 2-second step
    first = build_archive(project, registry, ref, odd)
    assert build_archive(project, registry, ref, odd) == first
    json_text = open_zip(first).read("lieux_varies.json").decode("utf-8")
    assert '"generated_at": "2026-11-07T14:30:13"' in json_text


def test_readme_attributes_paris_table(
    project: Project, registry: PlaceRegistry, ref: RefData
) -> None:
    archive = open_zip(build_archive(project, registry, ref, GENERATED_AT))
    readme = archive.read("LISEZMOI.txt").decode("utf-8")
    table = project.paris_table
    assert "ODbL" in readme and "ALPAGE" in readme
    assert table.attribution.strip().splitlines()[2].strip() in readme
    assert table.extraction in readme
    assert "Arrondissements" in readme and "precisions_occurrences" in readme
    assert "{" not in readme


DICOTOPO_DEPARTMENTS = {"62": "2026-11-08"}
FIXTURE_XML = FIXTURES / "dicotopo" / "DT62.xml"


def ancient_forms() -> list[str]:
    root = ET.parse(FIXTURE_XML).getroot()
    forms = [
        "".join(i.itertext()).strip(" ,")
        for f in root.iter("forme_ancienne")
        for i in f.iter("i")
    ]
    assert "Fictimons" in forms and "Fictimontem" in forms
    return forms


@pytest.fixture
def dicotopo_project(tmp_path: Path, registry: PlaceRegistry, ref: RefData) -> Project:
    gw = tmp_path / "bases" / "lieux_dicotopo.gw"
    gw.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "lieux_dicotopo.gw", gw)
    registry.validate(
        ["Fictimont, Hesdin-la-Forêt"],
        [
            Level(
                0,
                "Fictimont",
                type="lieu_dit",
                identifier="P90000002",
                source="DicoTopo, https://dicotopo.cths.fr/places/P90000002",
                origin="dicotopo",
            ),
            Level(
                1, "Hesdin-la-Forêt", type="commune", identifier="62447", origin="insee"
            ),
        ],
        None,
        None,
        project="p",
    )
    return Project.open(gw, registry, ref, tmp_path / "data" / "projects")


def test_dicotopo_level_exported_with_link(
    dicotopo_project: Project, registry: PlaceRegistry, ref: RefData
) -> None:
    archive = open_zip(
        build_archive(
            dicotopo_project, registry, ref, GENERATED_AT, DICOTOPO_DEPARTMENTS
        )
    )
    rows = [
        r
        for r in json.loads(archive.read("lieux_dicotopo.json"))["tables"][
            "niveaux_lieux"
        ]
        if r["origine"] == "dicotopo"
    ]
    assert len(rows) == 1
    assert rows[0]["identifiant"] == "P90000002"
    assert rows[0]["nom"] == "Fictimont"
    assert rows[0]["source"] == "DicoTopo, https://dicotopo.cths.fr/places/P90000002"


def test_no_ancient_form_in_export(
    dicotopo_project: Project, registry: PlaceRegistry, ref: RefData
) -> None:
    archive = open_zip(
        build_archive(
            dicotopo_project, registry, ref, GENERATED_AT, DICOTOPO_DEPARTMENTS
        )
    )
    forms = ancient_forms()
    assert len(forms) >= 2
    for name in archive.namelist():
        data = archive.read(name)
        for form in forms:
            assert form.encode("utf-8") not in data, (name, form)


def test_readme_cites_dicotopo_only_when_used(
    project: Project,
    dicotopo_project: Project,
    registry: PlaceRegistry,
    ref: RefData,
    lyon: str,
) -> None:
    used = (
        open_zip(
            build_archive(
                dicotopo_project, registry, ref, GENERATED_AT, DICOTOPO_DEPARTMENTS
            )
        )
        .read("LISEZMOI.txt")
        .decode("utf-8")
    )
    assert "DicoTopo (CTHS, École nationale des chartes)" in used
    assert "CC BY-NC-ND 3.0 FR" in used
    assert "Département 62 : téléchargé le 2026-11-08." in used
    assert "{" not in used
    unused = (
        open_zip(
            build_archive(project, registry, ref, GENERATED_AT, DICOTOPO_DEPARTMENTS)
        )
        .read("LISEZMOI.txt")
        .decode("utf-8")
    )
    assert "CTHS" not in unused and "CC BY-NC-ND" not in unused
    # no sources: the notice stays, without any department
    bare = (
        open_zip(build_archive(dicotopo_project, registry, ref, GENERATED_AT))
        .read("LISEZMOI.txt")
        .decode("utf-8")
    )
    assert "CC BY-NC-ND 3.0 FR" in bare and "Département 62" not in bare


GEONAMES_COUNTRIES = {"CA": "2026-11-08"}


@pytest.fixture
def geonames_project(tmp_path: Path, registry: PlaceRegistry, ref: RefData) -> Project:
    gw = tmp_path / "bases" / "lieux_geonames.gw"
    gw.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "lieux_geonames.gw", gw)
    registry.validate(
        ["Winnipeg, Manitoba, Canada"],
        [
            Level(
                0,
                "Winnipeg",
                type="localite",
                identifier="9000001",
                source="GeoNames 2026-11-08",
                latitude=49.9,
                longitude=-97.1,
                origin="geonames",
            ),
            Level(1, "Manitoba", type="province", origin="geonames"),
            Level(2, "Canada", type="pays", origin="written"),
        ],
        None,
        None,
        project="p",
    )
    return Project.open(gw, registry, ref, tmp_path / "data" / "projects")


def test_geonames_level_exported(
    geonames_project: Project, registry: PlaceRegistry, ref: RefData
) -> None:
    archive = open_zip(
        build_archive(
            geonames_project,
            registry,
            ref,
            GENERATED_AT,
            geonames_countries=GEONAMES_COUNTRIES,
        )
    )
    rows = [
        r
        for r in json.loads(archive.read("lieux_geonames.json"))["tables"][
            "niveaux_lieux"
        ]
        if r["origine"] == "geonames" and r["rang"] == 0
    ]
    assert len(rows) == 1
    assert rows[0]["identifiant"] == "9000001"
    assert rows[0]["source"] == "GeoNames 2026-11-08"


def test_readme_cites_geonames_only_when_used(
    project: Project,
    geonames_project: Project,
    registry: PlaceRegistry,
    ref: RefData,
    lyon: str,
) -> None:
    used = (
        open_zip(
            build_archive(
                geonames_project,
                registry,
                ref,
                GENERATED_AT,
                geonames_countries=GEONAMES_COUNTRIES,
            )
        )
        .read("LISEZMOI.txt")
        .decode("utf-8")
    )
    assert "GeoNames" in used and "CC BY 4.0" in used
    assert "https://www.geonames.org/" in used
    assert "Pays CA : données du 2026-11-08." in used
    assert "Pays CA : téléchargé le" not in used
    assert "{" not in used
    unused = (
        open_zip(
            build_archive(
                project,
                registry,
                ref,
                GENERATED_AT,
                geonames_countries=GEONAMES_COUNTRIES,
            )
        )
        .read("LISEZMOI.txt")
        .decode("utf-8")
    )
    assert "CC BY 4.0" not in unused and "geonames.org" not in unused
    bare = (
        open_zip(build_archive(geonames_project, registry, ref, GENERATED_AT))
        .read("LISEZMOI.txt")
        .decode("utf-8")
    )
    assert "CC BY 4.0" in bare and "données du" not in bare
