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


def test_same_name_on_level_and_upper_level(
    source: GeoNamesSource, ref: RefData
) -> None:
    levels = rule_levels(decompose("Quebec, Quebec, Canada", ref), ref)
    queries = queries_for(levels, "CA")
    assert [q.role for q in queries] == ["level", "upper"]
    found = search_all(source, levels, "CA")
    assert {c.role for c in found} == {"level", "upper"}
    chain, alternatives = proposals(levels, found)
    assert alternatives == ()
    check_chain(chain)
    assert [(lv.name, lv.type, lv.identifier) for lv in chain[:2]] == [
        ("Quebec", "localite", "9000010"),
        ("Quebec", "province", "9000011"),
    ]


def test_role_in_key_and_queue_payload() -> None:
    from prosopo_gw_atelier.sources.base import LevelQuery
    from prosopo_gw_atelier.sources.queue import match_payload

    level = LevelQuery(name="Ontario", country="CA")
    upper = LevelQuery(name="Ontario", country="CA", role="upper")
    assert level.key() != upper.key()
    assert '"role"' not in level.key()  # keys already stored stay valid
    assert match_payload(upper)["role"] == "upper"


def test_upper_query_never_uses_the_api(tmp_path: Path, ref: RefData) -> None:
    from prosopo_gw_atelier.sources.base import LevelQuery

    calls: list[object] = []

    def opener(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("no request expected")

    idx = GeoNamesIndex(tmp_path / "geonames")  # no country indexed
    api = GeoNamesSource(
        idx,
        config=LocalConfig(geonames_username="user-x"),
        counter_path=tmp_path / "api_counter.json",
        opener=opener,  # type: ignore[arg-type]
    )
    upper = LevelQuery(name="Ontario", country="CA", role="upper")
    assert api.can_answer(upper) is False
    assert api.can_answer(LevelQuery(name="Ontario", country="CA")) is True
    assert api.search(upper) == []
    assert calls == []
    # without upper candidates the candidate's own parents are all there is
    levels = rule_levels(decompose("Winnipeg, Ontario, Canada", ref), ref)
    winnipeg = SourceCandidate(
        source="geonames",
        identifier="1",
        name="Winnipeg",
        type="localite",
        feature_code="PPL",
        parents=(
            Level(1, "Manitoba", type="province", origin="geonames", status="proposed"),
        ),
    )
    chain, _ = proposals(levels, [winnipeg])
    check_chain(chain)
    assert "Manitoba" in proposed(chain)


def test_written_division_in_another_language_is_matched(
    source: GeoNamesSource, ref: RefData
) -> None:
    # "Angleterre" is an alternate name of England: it is typed in place, not doubled.
    levels = rule_levels(decompose("Storrington, Angleterre, Royaume-Uni", ref), ref)
    chain, _ = proposals(levels, search_all(source, levels, "GB"))
    untouched(chain, levels)
    england = proposed(chain)["England"]
    assert england.written == "Angleterre"
    assert [lv.name for lv in chain].count("England") == 1
    assert "Angleterre" not in [lv.name for lv in chain]


def _division(identifier: str, name: str, asked: str) -> SourceCandidate:
    return SourceCandidate(
        source="geonames",
        identifier=identifier,
        name=name,
        type="comte",
        feature_code="ADM2",
        role="upper",
        asked=asked,
    )


def _town(identifier: str, county: Level) -> SourceCandidate:
    return SourceCandidate(
        source="geonames",
        identifier=identifier,
        name="Bourg",
        type="localite",
        feature_code="PPL",
        parents=(county,),
    )


def test_translated_division_picks_its_homonym() -> None:
    levels = [
        Level(0, "Bourg", origin="written"),
        Level(1, "Grand Nord", origin="written"),
        Level(2, "Pays", type="pays", origin="written"),
    ]
    north = Level(1, "Greater North", type="comte", identifier="10")
    south = Level(1, "Greater South", type="comte", identifier="20")
    candidates = [
        _town("1", north),
        _town("2", south),
        _division("10", "Greater North", "Grand Nord"),
    ]
    chain, alternatives = proposals(levels, candidates)
    assert alternatives == ()
    assert proposed(chain)["Bourg"].identifier == "1"
    county = proposed(chain)["Greater North"]
    assert county.written == "Grand Nord" and county.rank == 1
    assert len(chain) == 3


def test_division_found_for_two_written_names_keeps_both() -> None:
    """A division returned for two written levels names both, whatever the order."""
    levels = [
        Level(0, "Bourg", origin="written"),
        Level(1, "Beta", origin="written"),
        Level(2, "Alpha", origin="written"),
        Level(3, "Pays", type="pays", origin="written"),
    ]
    ten = Level(1, "Division Ten", type="comte", identifier="10")
    twenty = Level(1, "Division Twenty", type="comte", identifier="20")
    for alpha_first in (True, False):
        alpha = [
            _division("10", "Division Ten", "Alpha"),
            _division("20", "Division Twenty", "Alpha"),
        ]
        beta = [_division("10", "Division Ten", "Beta")]
        uppers = alpha + beta if alpha_first else beta + alpha
        chain, alternatives = proposals(
            levels, [_town("1", ten), _town("2", twenty), *uppers]
        )
        assert alternatives == ()
        assert proposed(chain)["Bourg"].identifier == "1", alpha_first
