"""Tests of the GeoNames level-chain proposals (synthetic fixtures only)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.levels import (
    FOREIGN_TYPES,
    Level,
    check_chain,
    rule_levels,
)
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.sources.base import SourceCandidate
from prosopo_gw_atelier.sources.geonames.index import GeoNamesIndex
from prosopo_gw_atelier.sources.geonames.source import (
    GeoNamesSource,
    proposals,
    queries_for,
)
from prosopo_gw_atelier.sources.geonames.types import ADMIN_TYPES, level_type
from prosopo_gw_atelier.store.config import LocalConfig

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GN = FIXTURES / "geonames"
Chain = tuple[tuple[Level, ...], tuple[tuple[Level, ...], ...]]


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


@pytest.fixture
def source(tmp_path: Path) -> GeoNamesSource:
    idx = GeoNamesIndex(tmp_path / "geonames")
    for cc in ("CA", "GB", "JP"):
        idx.build(
            cc,
            GN / f"{cc}.zip",
            GN / "admin1CodesASCII.txt",
            GN / "admin2Codes.txt",
            "2026-11-08",
        )
    return GeoNamesSource(
        idx, config=LocalConfig(), counter_path=tmp_path / "api_counter.json"
    )


def search_all(
    source: GeoNamesSource, levels: Sequence[Level], iso: str
) -> list[SourceCandidate]:
    found: list[SourceCandidate] = []
    for query in queries_for(levels, iso):
        found += source.search(query)
    return found


def run(source: GeoNamesSource, ref: RefData, writing: str, iso: str) -> Chain:
    levels = rule_levels(decompose(writing, ref), ref)
    return proposals(levels, search_all(source, levels, iso))


def proposed(chain: Sequence[Level]) -> dict[str, Level]:
    """Proposed levels by name (GeoNames name, or the written one if it is kept)."""
    check_chain(chain)
    return {lv.name: lv for lv in chain if lv.status == "proposed"}


def untouched(chain: Sequence[Level], levels: Sequence[Level]) -> None:
    """Nothing written is lost: each input level is kept as is (ranks aside), or
    proposed in place with its written name kept (in ``name`` or ``written``)."""
    check_chain(chain)
    plain = [replace(lv, rank=0) for lv in chain if lv.status == "validated"]
    for lv in levels:
        if replace(lv, rank=0) in plain:
            continue
        assert any(
            p.status == "proposed" and lv.name in (p.name, p.written) for p in chain
        ), lv


def test_level_type_table() -> None:
    assert level_type("PPLA", "CA") == "localite"
    assert level_type("PPL", "ZZ") == "localite"
    assert level_type("ADM1", "CA") == "province"
    assert level_type("ADM2", "CA") is None
    assert level_type("ADM1", "NL") == "province"
    assert level_type("ADM2", "NL") is None
    assert level_type("ADM1", "BE") is None
    assert level_type("ADM2", "BE") == "province"
    assert level_type("ADM1", "ZZ") is None
    assert level_type("MT", "CA") is None
    for codes in ADMIN_TYPES.values():
        for t in codes:
            assert t is None or t in FOREIGN_TYPES
    for country in ADMIN_TYPES:
        for code in ("PPL", "PPLA", "ADM1", "ADM2", "ADM3", "PCLI"):
            t = level_type(code, country)
            assert t is None or t in FOREIGN_TYPES


def test_queries_for_level_zero_with_written_parents(ref: RefData) -> None:
    levels = rule_levels(decompose("Winnipeg, , , Manitoba, Canada", ref), ref)
    query, upper = queries_for(levels, "CA")
    assert (query.name, query.country, query.parents) == (
        "Winnipeg",
        "CA",
        ("Manitoba",),
    )
    assert (upper.name, upper.country, upper.parents) == ("Manitoba", "CA", ())
    assert queries_for(levels, "Canada") == []
    assert queries_for([], "CA") == []
    typed = [replace(levels[0], type="localite"), *levels[1:]]
    assert queries_for(typed, "CA") == []


def test_winnipeg_gets_types_and_identifier(
    source: GeoNamesSource, ref: RefData
) -> None:
    levels = rule_levels(decompose("Winnipeg, , , Manitoba, Canada", ref), ref)
    chain, alternatives = proposals(levels, search_all(source, levels, "CA"))
    assert alternatives == ()
    by_name = proposed(chain)
    assert by_name["Winnipeg"].type == "localite"
    identifier = by_name["Winnipeg"].identifier
    assert identifier is not None and identifier.isdigit()
    assert by_name["Winnipeg"].source == "GeoNames 2026-11-08"
    assert by_name["Winnipeg"].origin == "geonames"
    assert by_name["Winnipeg"].latitude == pytest.approx(49.88)
    assert by_name["Manitoba"].type == "province"
    untouched(chain, levels)  # nothing overwritten
    assert [(lv.name, lv.status) for lv in chain] == [
        ("Winnipeg", "proposed"),
        ("Manitoba", "proposed"),
        ("Canada", "validated"),
    ]
    assert by_name["Winnipeg"].rank == 0 and by_name["Manitoba"].rank == 1


def test_storrington_keeps_four_levels_and_adds_types(
    source: GeoNamesSource, ref: RefData
) -> None:
    writing = "Storrington, East Sussex, England, United Kingdom"
    levels = rule_levels(decompose(writing, ref), ref)
    chain, alternatives = proposals(levels, search_all(source, levels, "GB"))
    assert alternatives == ()
    by_name = proposed(chain)
    assert by_name["East Sussex"].type == "comte"
    assert by_name["England"].type == "nation_constitutive"
    assert by_name["Storrington"].type == "localite"
    assert "United Kingdom" not in by_name
    untouched(chain, levels)
    assert [lv.status for lv in chain] == ["proposed"] * 3 + ["validated"]


def test_missing_province_is_added(source: GeoNamesSource, ref: RefData) -> None:
    levels = rule_levels(decompose("Winnipeg, Canada", ref), ref)
    chain, _ = proposals(levels, search_all(source, levels, "CA"))
    assert [(lv.name, lv.status) for lv in chain] == [
        ("Winnipeg", "proposed"),
        ("Manitoba", "proposed"),
        ("Canada", "validated"),
    ]
    untouched(chain, levels)
    manitoba = proposed(chain)["Manitoba"]
    assert manitoba.type == "province" and manitoba.identifier == "9000002"


def test_unknown_written_level_stays(source: GeoNamesSource, ref: RefData) -> None:
    levels = rule_levels(decompose("Winnipeg, Prusse-Fictive, Canada", ref), ref)
    chain, _ = proposals(levels, search_all(source, levels, "CA"))
    untouched(chain, levels)
    names = [lv.name for lv in chain]
    assert "Prusse-Fictive" in names
    assert "Prusse-Fictive" not in proposed(chain)
    assert proposed(chain)["Manitoba"].type == "province"


def test_written_name_differs_from_geonames(
    source: GeoNamesSource, ref: RefData
) -> None:
    levels = rule_levels(decompose("Ouinipègue, Manitoba, Canada", ref), ref)
    chain, _ = proposals(levels, search_all(source, levels, "CA"))
    twin = proposed(chain)["Winnipeg"]
    assert twin.written == "Ouinipègue" and twin.rank == 0
    assert twin.identifier == "9000001"
    untouched(chain, levels)


def test_homonyms_without_parents_give_alternatives(
    source: GeoNamesSource, ref: RefData
) -> None:
    levels = rule_levels(decompose("Beaumont, Canada", ref), ref)
    chain, alternatives = proposals(levels, search_all(source, levels, "CA"))
    assert chain == ()
    assert len(alternatives) == 2
    first, second = (proposed(alt) for alt in alternatives)
    # most populous first, but nothing is picked
    assert first["Beaumont"].identifier == "9000004"
    assert first["Manitoba"].identifier == "9000002"
    assert second["Beaumont"].identifier == "9000005"
    assert second["Ontario"].type == "province"
    for alt in alternatives:
        untouched(alt, levels)


def test_alternatives_are_capped_and_ordered() -> None:
    levels = [Level(0, "Bourg", origin="written"), Level(1, "Pays", type="pays")]
    candidates = [
        SourceCandidate(
            source="geonames",
            identifier=str(i),
            name="Bourg",
            type="localite",
            feature_code="PPL",
            population=i * 10,
        )
        for i in range(1, 9)
    ]
    chain, alternatives = proposals(levels, candidates)
    assert chain == ()
    ids = [proposed(alt)["Bourg"].identifier for alt in alternatives]
    assert ids == ["8", "7", "6", "5", "4"]


def test_parents_disambiguate_homonyms(source: GeoNamesSource, ref: RefData) -> None:
    levels = rule_levels(decompose("Beaumont, Ontario, Canada", ref), ref)
    chain, alternatives = proposals(levels, search_all(source, levels, "CA"))
    assert alternatives == ()
    assert proposed(chain)["Beaumont"].identifier == "9000005"
    assert proposed(chain)["Ontario"].type == "province"
    untouched(chain, levels)
    check_chain(chain)
    assert len(chain) == 3


def test_homonyms_in_same_division_stay_alternatives(
    source: GeoNamesSource, ref: RefData
) -> None:
    chain, alternatives = run(source, ref, "Rosedale, Manitoba, Canada", "CA")
    assert chain == () and len(alternatives) == 2


def test_country_without_admin_types_gets_identifier_only(
    source: GeoNamesSource, ref: RefData
) -> None:
    levels = rule_levels(decompose("Hanamura, Fictive Prefecture, Japon", ref), ref)
    chain, _ = proposals(levels, search_all(source, levels, "JP"))
    by_name = proposed(chain)
    assert by_name["Hanamura"].type == "localite"
    assert by_name["Fictive Prefecture"].type is None
    assert by_name["Fictive Prefecture"].identifier == "9300002"
    untouched(chain, levels)


def test_admin_division_alone_when_no_populated_place(
    source: GeoNamesSource, ref: RefData
) -> None:
    levels = rule_levels(decompose("Manitoba, Canada", ref), ref)
    chain, _ = proposals(levels, search_all(source, levels, "CA"))
    twin = proposed(chain)["Manitoba"]
    assert twin.type == "province" and twin.identifier == "9000002"
    check_chain(chain)
    assert len(chain) == 2


def test_no_candidate_gives_nothing(source: GeoNamesSource, ref: RefData) -> None:
    assert run(source, ref, "Nulle-Part, Canada", "CA") == ((), ())


def test_written_other_division_excludes_candidate(
    source: GeoNamesSource, ref: RefData
) -> None:
    assert run(source, ref, "Winnipeg, Ontario, Canada", "CA") == ((), ())


def test_fallback_keeps_only_admin_features() -> None:
    levels = [Level(0, "Pays-Fictif", origin="written")]
    country = SourceCandidate(
        source="geonames", identifier="1", name="Pays-Fictif", feature_code="PCLI"
    )
    assert proposals(levels, [country]) == ((), ())
    admin = SourceCandidate(
        source="geonames",
        identifier="2",
        name="Pays-Fictif",
        type="province",
        feature_code="ADM1",
    )
    chain, _ = proposals(levels, [country, admin])
    assert [lv.identifier for lv in chain] == ["2"]
