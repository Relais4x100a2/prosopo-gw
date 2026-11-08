"""Tests of the offline Paris street table builder ``atelier/tools/build_paris.py``.

The fixtures under ``fixtures/paris_sources`` mimic the Vasserot (ALPAGE) ArcGIS
layers and the Paris open data exports, with invented geometries.
"""

from __future__ import annotations

import csv
import gzip
import importlib.util
import io
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

ATELIER = Path(__file__).resolve().parents[2]
SOURCES = ATELIER / "tests" / "fixtures" / "paris_sources"


def _load_builder() -> ModuleType:
    path = ATELIER / "tools" / "build_paris.py"
    spec = importlib.util.spec_from_file_location("build_paris", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_paris"] = module
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


def read_gz_csv(path: Path) -> list[dict[str, str]]:
    text = gzip.decompress(path.read_bytes()).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


@pytest.fixture
def table(tmp_path: Path) -> Path:
    builder.build(SOURCES, tmp_path, date(2026, 11, 8))
    return tmp_path


def test_point_in_polygon_with_hole() -> None:
    outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]
    assert builder.point_in_polygon(1, 1, [outer, hole])
    assert not builder.point_in_polygon(5, 5, [outer, hole])
    assert not builder.point_in_polygon(11, 5, [outer, hole])


def test_midpoint_is_at_half_length() -> None:
    assert builder.midpoint([(0.0, 0.0), (10.0, 0.0)]) == (5.0, 0.0)
    # L-shaped line of length 4 + 12 = 16: the middle is 8 along, 4 up the second leg.
    assert builder.midpoint([(0.0, 0.0), (4.0, 0.0), (4.0, 12.0)]) == (4.0, 4.0)
    assert builder.midpoint([(2.0, 3.0), (2.0, 3.0)]) == (2.0, 3.0)


def test_build_from_synthetic_sources(table: Path) -> None:
    rows = read_gz_csv(table / "rues.csv.gz")
    assert {
        "cle": "rue saint honore",
        "periode": "paris-1795",
        "arrondissement_id": "paris-1795-04",
        "quartier_id": "QU13",
        "quartier": "Marchés",
    } in rows
    assert {
        "cle": "rue saint honore",
        "periode": "paris-1860",
        "arrondissement_id": "75101",
        "quartier_id": "paris-q-saint-germain-l-auxerrois",
        "quartier": "Saint-Germain-l'Auxerrois",
    } in rows
    assert any(
        r["cle"] == "rue vaugirard"
        and r["periode"] == "paris-1860"
        and r["arrondissement_id"] == "75115"
        for r in rows
    )
    assert any(
        r["periode"] == "paris-1860" and r["arrondissement_id"] == "75111" for r in rows
    )
    assert "extraction=2026-11-08" in (table / "VERSION").read_text()
    assert "source=https://" in (table / "VERSION").read_text()


def test_segment_outside_any_quartier_is_dropped(table: Path) -> None:
    keys = {r["cle"] for r in read_gz_csv(table / "rues.csv.gz")}
    assert "rue hors quartier" not in keys


def test_dropped_segments_are_counted_and_hole_counts_as_outside() -> None:
    result = builder.build_tables(SOURCES)
    # One segment far away, one whose midpoint falls in the hole of a quartier.
    assert result.dropped_segments == 2
    assert not any(r.key == "rue verrerie" for r in result.rows)


def test_street_in_two_arrondissements_keeps_both_rows(table: Path) -> None:
    rows = read_gz_csv(table / "rues.csv.gz")
    old = {
        r["arrondissement_id"]
        for r in rows
        if r["cle"] == "rue saint honore" and r["periode"] == "paris-1795"
    }
    assert old == {"paris-1795-04", "paris-1795-02"}
    new = {
        r["arrondissement_id"]
        for r in rows
        if r["cle"] == "rue vaugirard" and r["periode"] == "paris-1860"
    }
    assert new == {"75106", "75115"}


def test_faubourg_is_also_written_without_rue(table: Path) -> None:
    keys = {r["cle"] for r in read_gz_csv(table / "rues.csv.gz")}
    assert {"rue faubourg saint antoine", "faubourg saint antoine"} <= keys


def test_defunct_street_before_1860_is_ignored(table: Path) -> None:
    rows = read_gz_csv(table / "rues.csv.gz")
    keys = {r["cle"] for r in rows}
    assert "rue biron" not in keys
    assert "rue bella" in keys and "rue antoine reynier" in keys
    assert "rue beccaria" not in keys  # no arrondissement


def test_quartiers_and_annexed_communes(table: Path) -> None:
    quartiers = read_gz_csv(table / "quartiers.csv.gz")
    assert {
        "id": "QU13",
        "nom": "Marchés",
        "arrondissement_id": "paris-1795-04",
        "periode": "paris-1795",
    } in quartiers
    assert {
        "id": "paris-q-odeon",
        "nom": "Odéon",
        "arrondissement_id": "75106",
        "periode": "paris-1860",
    } in quartiers
    communes = {
        r["nom"]: r["arrondissement_ids"]
        for r in read_gz_csv(table / "communes_annexees.csv.gz")
    }
    assert len(communes) == 11
    assert communes["Vaugirard"] == "75115"
    assert communes["Belleville"] == "75119|75120"


def test_output_is_deterministic(tmp_path: Path) -> None:
    builder.build(SOURCES, tmp_path / "a", date(2026, 11, 8))
    builder.build(SOURCES, tmp_path / "b", date(2026, 11, 8))
    for name in ("rues.csv.gz", "quartiers.csv.gz", "communes_annexees.csv.gz"):
        assert (tmp_path / "a" / name).read_bytes() == (
            tmp_path / "b" / name
        ).read_bytes()


def test_defunct_street_with_several_quartiers_in_one_text(table: Path) -> None:
    # The defunct streets dataset joins quartier names in one text ("A, B").
    rows = read_gz_csv(table / "rues.csv.gz")
    pairs = {
        (r["quartier_id"], r["quartier"])
        for r in rows
        if r["cle"] == "rue duvergier" and r["periode"] == "paris-1860"
    }
    assert pairs == {
        ("paris-q-villette", "Villette"),
        ("paris-q-amerique", "Amérique"),
    }


def test_hors_paris_is_not_a_quartier(table: Path) -> None:
    rows = read_gz_csv(table / "rues.csv.gz")
    assert {
        "cle": "boulevard peripherique",
        "periode": "paris-1860",
        "arrondissement_id": "75112",
        "quartier_id": "",
        "quartier": "",
    } in rows
    assert not any("hors" in r["quartier_id"] for r in rows)
    quartiers = read_gz_csv(table / "quartiers.csv.gz")
    assert not any("hors" in q["id"] or "Hors" in q["nom"] for q in quartiers)
