"""Tests of the DicoTopo source and of its proposal rules (synthetic fixtures only)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import BinaryIO

import pytest

from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.levels import Level, rule_levels
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.sources.base import LevelQuery, SourceCandidate, SourceError
from prosopo_gw_atelier.sources.dicotopo.index import DicoTopoIndex
from prosopo_gw_atelier.sources.dicotopo.source import (
    API_URL,
    DICOTOPO,
    DicoTopoSource,
    article_link,
    proposals,
    queries_for,
)
from prosopo_gw_atelier.sources.queue import RateLimiter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DT = FIXTURES / "dicotopo"


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


@pytest.fixture
def index(tmp_path: Path) -> DicoTopoIndex:
    idx = DicoTopoIndex(tmp_path / "index.sqlite")
    idx.add_department("62", DT / "DT62.xml", "2026-11-08")
    idx.add_department("59", DT / "DT59.xml", "2026-11-08")
    return idx


@pytest.fixture
def source(index: DicoTopoIndex, ref: RefData) -> DicoTopoSource:
    return DicoTopoSource(index, ref, api_enabled=False)


def search_all(
    source: DicoTopoSource, levels: Sequence[Level], writing: str, ref: RefData
) -> list[SourceCandidate]:
    found: list[SourceCandidate] = []
    for query in queries_for(levels, decompose(writing, ref)):
        found += source.search(query)
    return found


def run(
    source: DicoTopoSource, ref: RefData, writing: str
) -> tuple[tuple[Level, ...], tuple[tuple[Level, ...], ...]]:
    levels = rule_levels(decompose(writing, ref), ref)
    return proposals(levels, search_all(source, levels, writing, ref))


def test_constants() -> None:
    assert DICOTOPO == "dicotopo"
    assert API_URL == "https://dicotopo.cths.fr/api/1.0/"
    assert article_link("P1") == "https://dicotopo.cths.fr/places/P1"


def test_hamlet_under_resolved_commune(source: DicoTopoSource, ref: RefData) -> None:
    chain, alternatives = run(source, ref, "Fictimont, Hesdin-la-Forêt")
    hamlet = chain[0]
    assert (hamlet.type, hamlet.origin, hamlet.status) == (
        "hameau",
        "dicotopo",
        "proposed",
    )
    assert hamlet.name == "Fictimont"
    assert hamlet.identifier == "P90000002"
    assert hamlet.source is not None and "dicotopo.cths.fr" in hamlet.source
    assert chain[1].type == "commune" and chain[1].status == "validated"
    assert alternatives == ()


def test_ancient_form_without_commune(source: DicoTopoSource, ref: RefData) -> None:
    chain, alternatives = run(source, ref, "Fictimontem, Pas-de-Calais")
    assert [lv.type for lv in chain] == ["hameau", "commune", "departement"]
    assert chain[0].name == "Fictimontem" and chain[0].identifier == "P90000002"
    assert (chain[1].identifier, chain[1].origin) == ("62447", "insee")
    assert chain[1].name == "Hesdin-la-Forêt"
    assert alternatives == ()


def test_insee_2011_brought_to_current_commune(
    source: DicoTopoSource, ref: RefData
) -> None:
    chain, _ = run(source, ref, "Le Fictibois, Nord")
    assert [lv.type for lv in chain] == [
        "lieu_dit",
        "commune_historique",
        "commune",
        "departement",
    ]
    assert chain[0].name == "Le Fictibois"
    assert (chain[1].name, chain[1].identifier, chain[1].nature) == (
        "Lomme",
        "59355",
        "associee",
    )
    assert (chain[2].name, chain[2].identifier) == ("Lille", "59350")


def test_commune_article_is_an_old_name(source: DicoTopoSource, ref: RefData) -> None:
    chain, _ = run(source, ref, "Hesdinum Fictivum, Pas-de-Calais")
    assert [lv.type for lv in chain] == ["commune", "departement"]
    assert (chain[0].name, chain[0].written) == ("Hesdin-la-Forêt", "Hesdinum Fictivum")
    assert chain[0].identifier == "62447" and chain[0].origin == "insee"


def test_never_changes_resolved_commune(source: DicoTopoSource, ref: RefData) -> None:
    # Fictimont belongs to Hesdin-la-Forêt: written under another commune, no proposal.
    levels = rule_levels(decompose("Fictimont, Arras", ref), ref)
    query = LevelQuery("Fictimont", department="62")
    assert source.search(query)  # the article exists in the department
    candidates = source.search(query)
    assert proposals(levels, candidates) == ((), ())
    assert search_all(source, levels, "Fictimont, Arras", ref) == []


def test_homonyms_give_alternatives(source: DicoTopoSource, ref: RefData) -> None:
    chain, alternatives = run(source, ref, "Le Quesnoy-Fictif, Pas-de-Calais")
    assert chain == ()
    assert len(alternatives) == 2
    communes = {
        next(lv for lv in alt if lv.type == "commune").name for alt in alternatives
    }
    assert len(communes) == 2
    assert {alt[0].identifier for alt in alternatives} == {"P90000003", "P90000004"}
    assert all(alt[0].status == "proposed" for alt in alternatives)


def test_resolved_commune_settles_homonyms(
    source: DicoTopoSource, ref: RefData
) -> None:
    chain, alternatives = run(source, ref, "Le Quesnoy-Fictif, Arras")
    assert chain[0].identifier == "P90000003" and alternatives == ()


def test_no_department_no_query(ref: RefData) -> None:
    levels = rule_levels(decompose("Fictimont", ref), ref)
    assert queries_for(levels, decompose("Fictimont", ref)) == []


def test_covers_and_article(source: DicoTopoSource) -> None:
    assert source.covers(LevelQuery("x", department="62"))
    assert not source.covers(LevelQuery("x", department="05"))
    found = source.article("P90000002")
    assert found is not None and found.insee == "62447" and found.type == "hameau"
    assert found.link == article_link("P90000002")
    assert source.article("P1") is None


class FakeApi:
    def __init__(self, status: int = 200) -> None:
        self.urls: list[str] = []
        self.status = status

    def __call__(self, request: urllib.request.Request, timeout: float) -> BinaryIO:
        url = request.full_url
        self.urls.append(url)
        if self.status != 200:
            raise urllib.error.HTTPError(url, self.status, "boom", None, None)  # type: ignore[arg-type]
        attributes = {
            "place-id": "P90000099",
            "place-label": "Fictiville (La)",
            "old-labels": ["<dfn>Fictivilla</dfn> (1200)"],
            "localization-insee-code": "05061",
            "commune-label": "Autre",
            "dpt": "05",
        }
        other = dict(attributes, dpt="06", **{"place-id": "P90000098"})
        body = {
            "data": [
                {"type": "place-old-label", "id": 1, "attributes": {"dpt": "05"}},
                {"type": "place", "id": "P90000099", "attributes": attributes},
                {"type": "place", "id": "P90000098", "attributes": other},
            ]
        }
        if "/places/" in url:
            body = {
                "data": {"type": "place", "id": "P90000099", "attributes": attributes}
            }
        return io.BytesIO(json.dumps(body).encode())  # type: ignore[return-value]


@pytest.fixture
def source_factory(index: DicoTopoIndex, ref: RefData) -> Callable[..., DicoTopoSource]:
    def make(api: FakeApi | None, enabled: bool = True) -> DicoTopoSource:
        return DicoTopoSource(
            index,
            ref,
            api_enabled=enabled,
            opener=api,
            limiter=RateLimiter(0, sleep=lambda s: None),
        )

    return make


def test_api_used_only_when_enabled_and_not_indexed(
    source_factory: Callable[..., DicoTopoSource], ref: RefData
) -> None:
    api = FakeApi()
    on = source_factory(api)
    on.search(LevelQuery("Fictimont", department="62"))  # indexed: no call
    assert api.urls == []
    on.search(LevelQuery("Fictiville", department="05"))
    assert len(api.urls) == 1 and api.urls[0].startswith(API_URL + "search?query=")
    off = source_factory(api, enabled=False)
    assert off.search(LevelQuery("Fictiville", department="05")) == []
    assert off.article("P90000099") is None
    assert len(api.urls) == 1


def test_api_search_filters_department_and_form(
    source_factory: Callable[..., DicoTopoSource], ref: RefData
) -> None:
    api = FakeApi()
    source = source_factory(api)
    for name in ("Fictiville", "Fictivilla", "La Fictiville"):
        found = source.search(LevelQuery(name, department="05"))
        # 05061 is unknown to the mini COG: the candidate cannot be placed.
        assert found == []
    article = source.article("P90000099")
    assert article is not None and article.insee is None
    assert article.name == "La Fictiville"
    assert api.urls[-1] == API_URL + "places/P90000099"
    assert source.article("../x") is None


def test_api_error_is_recorded(
    source_factory: Callable[..., DicoTopoSource],
) -> None:
    api = FakeApi(status=500)
    source = source_factory(api)
    with pytest.raises(SourceError):
        source.search(LevelQuery("Fictiville", department="05"))
    with pytest.raises(SourceError):
        source.search(LevelQuery("Fictiville", department="05"))
    assert len(api.urls) == 2  # nothing cached: the second call retries


def test_written_without_article_matches_inverted_headword(
    source: DicoTopoSource, ref: RefData
) -> None:
    for writing in ("Fictibois, Nord", "Le Fictibois, Nord"):
        chain, alternatives = run(source, ref, writing)
        assert chain[0].identifier == "P90000011" and alternatives == ()
        assert chain[0].name == writing.split(",")[0]


def test_mixed_single_and_ambiguous_targets_leave_chain_whole(
    source: DicoTopoSource, ref: RefData
) -> None:
    writing = "Fictimont, Le Quesnoy-Fictif, Pas-de-Calais"
    chain, alternatives = run(source, ref, writing)
    assert chain == ()
    assert len(alternatives) == 2


def test_lieu_dit_named_like_its_commune_is_not_a_commune() -> None:
    from prosopo_gw_atelier.sources.dicotopo.source import _api_article

    attributes = {
        "place-id": "P90000050",
        "place-label": "Fictiville",
        "commune-label": "Fictiville",
        "localization-insee-code": "05061",
        "dpt": 5,
        "place-feature-types": ["lieu-dit"],
    }
    entry = {"type": "place", "id": "P90000050", "attributes": attributes}
    article = _api_article(entry)
    assert article is not None and article.insee is None and article.department == "05"
    attributes["place-feature-types"] = ["commune"]
    article = _api_article(entry)
    assert article is not None and article.insee == "05061"
