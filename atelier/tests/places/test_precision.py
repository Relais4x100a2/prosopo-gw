"""Tests of the per-occurrence arrondissement precision."""

from __future__ import annotations

from pathlib import Path

import pytest

from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.levels import Level, rule_levels
from prosopo_gw_atelier.places.model import Occurrence, WrittenArrondissement
from prosopo_gw_atelier.places.precision import period_of, precise
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.refdata.paris_table import ParisTable, load_paris_table

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


@pytest.fixture(scope="module")
def table() -> ParisTable:
    return load_paris_table(FIXTURES / "paris_mini")


def occ(
    year: int | None = None,
    complement: str | None = None,
    date: str | None = None,
) -> Occurrence:
    if date is None and year is not None:
        date = str(year)
    return Occurrence(
        "personnes", "P1", "naissance_lieu", complement, "naissance", date, year
    )


def chain(ref: RefData, writing: str) -> tuple[Level, ...]:
    return rule_levels(decompose(writing, ref), ref)


def test_period_of() -> None:
    assert period_of("paris", 1859) == "paris-1795"
    assert period_of("paris", 1860) == "paris-1860"
    assert period_of("paris", None) == ""
    assert period_of("lyon", 1900) == "lyon"
    assert period_of("marseille", 1950) == "marseille"
    assert period_of("marseille", None) == ""


def test_same_number_in_1850_and_1870(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Paris 7e")
    arr = WrittenArrondissement("paris", 7, "number")
    p1850 = precise(levels, arr, occ(year=1850), table)
    p1870 = precise(levels, arr, occ(year=1870), table)
    assert p1850 is not None and p1870 is not None
    assert (p1850.period, p1850.status) == ("paris-1795", "applied")
    assert p1850.candidates[0].arrondissement_id == "paris-1795-07"
    assert (p1870.period, p1870.status) == ("paris-1860", "applied")
    assert p1870.candidates[0].arrondissement_id == "75107"


def test_number_unknown_before_1860(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Paris 15e")
    arr = WrittenArrondissement("paris", 15, "number")
    p = precise(levels, arr, occ(year=1850), table)
    assert p is not None
    assert p.status == "conflict"
    assert [c.arrondissement_id for c in p.candidates] == [""]


def test_postal_code_and_street_in_conflict(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "75007 Paris")
    arr = WrittenArrondissement("paris", 7, "code")
    p = precise(levels, arr, occ(year=1900, complement="rue Lecourbe"), table)
    assert p is not None
    assert p.status == "conflict"
    assert {c.clue for c in p.candidates} == {"code", "street"}
    assert {c.arrondissement_id for c in p.candidates} == {"75107", "75115"}


def test_code_and_street_agree_street_gives_quartier(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "75115 Paris")
    arr = WrittenArrondissement("paris", 15, "code")
    p = precise(levels, arr, occ(year=1900, complement="rue Lecourbe"), table)
    assert p is not None
    assert p.status == "applied"
    (c,) = p.candidates
    assert (c.arrondissement_id, c.quartier_id, c.clue) == (
        "75115",
        "paris-q-necker",
        "code",
    )
    assert c.quartier == "Necker"


def test_undated_occurrence_keeps_number_without_period(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Paris 7e")
    arr = WrittenArrondissement("paris", 7, "number")
    p = precise(levels, arr, occ(year=None, complement="rue Lecourbe"), table)
    assert p is not None
    assert (p.period, p.status) == ("", "applied")
    assert [c.arrondissement_id for c in p.candidates] == ["paris-07"]


def test_code_before_1860_is_uncertain(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "75007 Paris")
    arr = WrittenArrondissement("paris", 7, "code")
    p = precise(levels, arr, occ(year=1850), table)
    assert p is not None
    assert p.status == "uncertain"
    assert p.candidates[0].arrondissement_id == "75107"


def test_street_that_changed_arrondissement(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Paris")
    old = precise(levels, None, occ(year=1850, complement="rue Saint-Honoré"), table)
    new = precise(levels, None, occ(year=1890, complement="rue Saint-Honoré"), table)
    assert old is not None and new is not None
    assert old.period == "paris-1795"
    # Two arrondissements in 1795 for the same key: never guessed.
    assert old.status == "ambiguous"
    assert {c.arrondissement_id for c in old.candidates} == {
        "paris-1795-02",
        "paris-1795-04",
    }
    assert (new.status, new.candidates[0].arrondissement_id) == ("applied", "75101")
    assert new.candidates[0].clue == "street"
    assert new.candidates[0].quartier == "Saint-Germain-l'Auxerrois"


def test_number_picks_among_ambiguous_street_hits(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Paris 4e")
    arr = WrittenArrondissement("paris", 4, "number")
    p = precise(levels, arr, occ(year=1850, complement="rue Saint-Honoré"), table)
    assert p is not None
    assert p.status == "applied"
    (c,) = p.candidates
    assert (c.arrondissement_id, c.quartier_id, c.clue) == (
        "paris-1795-04",
        "QU13",
        "number",
    )


def test_street_in_two_arrondissements_is_ambiguous(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Paris")
    p = precise(levels, None, occ(year=1900, complement="rue de Vaugirard"), table)
    assert p is not None
    assert p.status == "ambiguous"
    assert {c.arrondissement_id for c in p.candidates} == {"75106", "75115"}


def test_street_in_two_quartiers_of_one_arrondissement(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Paris")
    p = precise(levels, None, occ(year=1900, complement="rue Duvergier"), table)
    assert p is not None
    assert p.status == "applied"
    (c,) = p.candidates
    assert (c.arrondissement_id, c.quartier_id, c.quartier) == ("75119", None, None)


def test_street_without_quartier(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Paris")
    p = precise(
        levels, None, occ(year=1900, complement="boulevard Périphérique"), table
    )
    assert p is not None and p.status == "applied"
    assert p.candidates[0].quartier_id is None


def test_plain_paris_gets_arrondissement_from_street(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Paris")
    p = precise(levels, None, occ(year=1900, complement="12, rue Tournon"), table)
    assert p is not None
    assert p.status == "applied"
    assert p.candidates[0].arrondissement_id == "75106"


def test_plain_paris_without_clue_is_none(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Paris")
    assert precise(levels, None, occ(year=1900), table) is None
    assert precise(levels, None, occ(year=1900, complement="chez lui"), table) is None
    # Undated: the street is not read.
    assert precise(levels, None, occ(complement="rue Tournon"), table) is None
    assert (
        precise(levels, None, occ(year=1900, complement="rue Inconnue"), table) is None
    )


def test_transition_year_is_uncertain(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Paris 7e")
    arr = WrittenArrondissement("paris", 7, "number")
    p = precise(levels, arr, occ(year=1860), table)
    assert p is not None
    assert (p.period, p.status) == ("paris-1860", "uncertain")
    assert p.candidates[0].arrondissement_id == "75107"


@pytest.mark.parametrize(
    ("date", "year"), [("~1860", 1860), ("<1861", 1861), ("1858..1862", 1858)]
)
def test_approximate_date_near_transition_is_uncertain(
    ref: RefData, table: ParisTable, date: str, year: int
) -> None:
    levels = chain(ref, "Paris 7e")
    arr = WrittenArrondissement("paris", 7, "number")
    p = precise(levels, arr, occ(year=year, date=date), table)
    assert p is not None
    assert p.status == "uncertain"


def test_approximate_date_far_from_transition_is_applied(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Paris 7e")
    arr = WrittenArrondissement("paris", 7, "number")
    p = precise(levels, arr, occ(year=1900, date="~1900"), table)
    assert p is not None and p.status == "applied"


def test_lyon_ignores_street_and_dates_before_creation(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Lyon 8e")
    arr = WrittenArrondissement("lyon", 8, "number")
    early = precise(levels, arr, occ(year=1950, complement="rue Tournon"), table)
    late = precise(levels, arr, occ(year=1960, complement="rue Tournon"), table)
    assert early is not None and late is not None
    assert (early.period, early.status) == ("lyon", "uncertain")
    assert (late.status, late.candidates[0].arrondissement_id) == ("applied", "69388")
    undated = precise(levels, arr, occ(), table)
    assert undated is not None
    assert (undated.period, undated.status) == ("", "applied")


def test_lyon_without_arrondissement_is_none(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Lyon")
    assert (
        precise(levels, None, occ(year=1900, complement="rue Tournon"), table) is None
    )


def test_marseille_before_creation_is_uncertain(
    ref: RefData, table: ParisTable
) -> None:
    levels = chain(ref, "Marseille 2e")
    arr = WrittenArrondissement("marseille", 2, "number")
    p = precise(levels, arr, occ(year=1900), table)
    assert p is not None and p.status == "uncertain"
    q = precise(levels, arr, occ(year=1970), table)
    assert q is not None
    assert (q.status, q.candidates[0].arrondissement_id) == ("applied", "13202")


def test_outside_the_three_cities_is_none(ref: RefData, table: ParisTable) -> None:
    levels = chain(ref, "Lille")
    arr = WrittenArrondissement("paris", 7, "number")
    assert precise(levels, arr, occ(year=1900), table) is None
    assert (
        precise(levels, None, occ(year=1900, complement="rue Tournon"), table) is None
    )
