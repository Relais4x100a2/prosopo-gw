"""Tests of the Paris street table loader."""

from __future__ import annotations

from pathlib import Path

from prosopo_gw_atelier.refdata.paris_table import (
    ParisTable,
    StreetHit,
    load_paris_table,
)

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "paris_mini"


def test_lookup_by_period() -> None:
    table = load_paris_table(MINI)
    old = table.streets("rue saint honore", "paris-1795")
    assert {h.arrondissement_id for h in old} == {"paris-1795-04", "paris-1795-02"}
    assert StreetHit("paris-1795-04", "QU13", "Marchés") in old
    new = table.streets("rue saint honore", "paris-1860")
    assert [h.arrondissement_id for h in new] == ["75101"]
    assert {
        h.arrondissement_id for h in table.streets("rue vaugirard", "paris-1860")
    } == {
        "75106",
        "75115",
    }


def test_unknown_street_is_empty() -> None:
    table = load_paris_table(MINI)
    assert table.streets("rue inconnue", "paris-1860") == ()
    assert table.streets("rue saint honore", "") == ()


def test_annexed_communes() -> None:
    table = load_paris_table(MINI)
    assert table.annexed("belleville") == ("75119", "75120")
    assert table.annexed("nulle part") == ()


def test_attribution_names_every_source() -> None:
    table = load_paris_table(MINI)
    assert "ALPAGE" in table.attribution and "Ville de Paris" in table.attribution
    assert table.extraction == "2026-11-08"


def test_table_is_cached() -> None:
    assert load_paris_table(MINI) is load_paris_table(MINI)
    assert isinstance(load_paris_table(MINI), ParisTable)


def test_shipped_table_loads() -> None:
    table = load_paris_table()
    assert table.extraction
    assert table.quartier_count("paris-1795") >= 40
    assert table.streets("rue saint honore", "paris-1860")
    assert "ODbL" in (table.directory / "LICENCE.txt").read_text(encoding="utf-8")


def test_empty_quartier_is_none() -> None:
    table = load_paris_table(MINI)
    assert table.streets("boulevard peripherique", "paris-1860") == (
        StreetHit("75112", None, None),
    )


def test_shipped_table_has_no_hors_paris_quartier() -> None:
    table = load_paris_table()
    hits = [
        h
        for key in ("rue saint honore", "rue vaugirard", "rue lecourbe")
        for h in table.streets(key, "paris-1860")
    ]
    assert hits
    import csv
    import gzip

    path = table.directory / "quartiers.csv.gz"
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    assert not any(
        "hors" in r["id"].lower() or "hors" in r["nom"].lower() for r in rows
    )
    ids = [r["id"] for r in rows if r["periode"] == "paris-1860"]
    assert len(set(ids)) == 80
    with gzip.open(
        table.directory / "rues.csv.gz", "rt", encoding="utf-8", newline=""
    ) as handle:
        assert not any(
            "hors" in r["quartier_id"] or "Hors" in r["quartier"]
            for r in csv.DictReader(handle, delimiter=";")
        )
