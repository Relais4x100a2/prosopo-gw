from pathlib import Path

import pytest

from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.model import Decomposition, Element
from prosopo_gw_atelier.refdata import Former, RefData, load_refdata

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "refdata_mini"


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(MINI)


def kinds(result: Decomposition) -> dict[str, Element]:
    return {element.kind: element for element in result.elements}


@pytest.mark.parametrize(
    ("writing", "insee", "expected"),
    [
        (
            "ROUBAIX, Nord, France",
            "59512",
            {"commune": "Roubaix", "department": "59", "country": "France"},
        ),
        ("59100 Roubaix", "59512", {"postal_code": "59100", "commune": "Roubaix"}),
        ("Roubaix 59100", "59512", {"postal_code": "59100", "commune": "Roubaix"}),
        ("Roubaix-59100", "59512", {"postal_code": "59100", "commune": "Roubaix"}),
        ("59512", "59512", {"insee_code": "59512"}),
        (
            "roubaix, Nord-Pas-de-Calais",
            "59512",
            {"commune": "Roubaix", "region": "Nord-Pas-de-Calais"},
        ),
        ("St-Omer (62)", "62765", {"commune": "Saint-Omer", "department": "62"}),
        ("Lyon", "69123", {"commune": "Lyon"}),
        ("Lille, France", "59350", {"commune": "Lille", "country": "France"}),
        ("Lomme", "59350", {"former_name": "Lomme"}),
        ("Merville, Nord", "59400", {"commune": "Merville", "department": "59"}),
        ("Merville (31)", "31341", {"commune": "Merville", "department": "31"}),
        ("Merville 59660", "59400", {"commune": "Merville", "postal_code": "59660"}),
    ],
)
def test_decompose(
    ref: RefData, writing: str, insee: str, expected: dict[str, str]
) -> None:
    result = decompose(writing, ref)
    assert result.writing == writing
    assert result.insee == insee
    assert result.ambiguous is False
    assert {k: e.value for k, e in kinds(result).items()} == expected


@pytest.mark.parametrize(
    ("writing", "kind", "hint"),
    [
        ("Roubaix", "commune", "nom"),
        ("59100 Roubaix", "postal_code", "code postal"),
        ("59512", "insee_code", "code INSEE"),
        ("ROUBAIX, Nord", "department", "département"),
        ("roubaix, Nord-Pas-de-Calais", "region", "ancienne région"),
        ("Roubaix, Hauts-de-France", "region", "région"),
        ("Roubaix, France", "country", "pays"),
        ("Lomme", "former_name", "ancien nom"),
    ],
)
def test_hints(ref: RefData, writing: str, kind: str, hint: str) -> None:
    assert kinds(decompose(writing, ref))[kind].hint == hint


def test_homonym_alone(ref: RefData) -> None:
    result = decompose("Merville", ref)
    assert result.insee is None
    assert result.candidates == ("31341", "59400")
    assert result.ambiguous is False


def test_unknown_code_is_ambiguous(ref: RefData) -> None:
    result = decompose("99999", ref)
    assert result.ambiguous is True
    assert result.insee is None
    assert result.elements == ()
    assert result.candidates == ()


def test_postal_code_alone_proposes_without_choosing(ref: RefData) -> None:
    result = decompose("59100", ref)
    assert result.insee is None
    assert result.candidates == ("59512",)
    assert [e.kind for e in result.elements] == ["postal_code"]


def test_postal_code_of_several_communes(ref: RefData) -> None:
    # 59000 is Lille's only in the mini data; Lyon's arrondissements all map to Lyon.
    result = decompose("69003", ref)
    assert result.insee is None
    assert result.candidates == ("69123",)


def test_unknown_segment_yields_no_element(ref: RefData) -> None:
    result = decompose("En mer", ref)
    assert result.elements == ()
    assert result.insee is None
    assert result.candidates == ()
    assert result.ambiguous is False


def test_complement_style_text_is_ignored(ref: RefData) -> None:
    result = decompose("Roubaix, rue Imaginaire", ref)
    assert result.insee == "59512"
    assert [e.kind for e in result.elements] == ["commune"]


def test_elements_follow_writing_order(ref: RefData) -> None:
    result = decompose("France, Nord, Roubaix", ref)
    assert [e.kind for e in result.elements] == ["country", "department", "commune"]
    assert result.insee == "59512"


@pytest.mark.parametrize(
    "writing",
    ["", "   ", ",,, ( ) - ", '/?#"', "Roubaix" * 2000, 'a/b?c#d"e', "2A004"],
)
def test_odd_input_never_raises(ref: RefData, writing: str) -> None:
    result = decompose(writing, ref)
    assert isinstance(result, Decomposition)
    assert result.insee is None


def test_deterministic(ref: RefData) -> None:
    assert decompose("Merville", ref) == decompose("Merville", ref)


def test_foreign_levels_are_all_kept(ref: RefData) -> None:
    d = decompose("Winnipeg, , , Manitoba, Canada", ref)
    assert [s.text for s in d.segments] == ["Winnipeg", "Manitoba", "Canada"]
    assert [s.element.kind if s.element else None for s in d.segments] == [
        None,
        None,
        "country",
    ]


def test_four_written_levels(ref: RefData) -> None:
    d = decompose("Storrington, , East Sussex, England, Royaume-Uni", ref)
    assert [s.text for s in d.segments] == [
        "Storrington",
        "East Sussex",
        "England",
        "Royaume-Uni",
    ]


def test_delegated_commune_is_historical(ref: RefData) -> None:
    d = decompose("Marconne, Pas-de-Calais", ref)
    assert d.insee == "62447"
    assert d.historical == Former(
        "Marconne", "62549", "62447", "deleguee", "2025-01-01"
    )


def test_rename_is_not_historical(ref: RefData) -> None:
    d = decompose("Saint-Omer-en-Artois", ref)
    assert d.insee == "62765" and d.historical is None
    assert [e.kind for e in d.elements] == ["former_name"]


def test_current_name_with_former_alternative(ref: RefData) -> None:
    d = decompose("Sainte-Austreberthe, Seine-Maritime", ref)
    assert d.insee == "76566" and d.historical is None
    assert d.alternative is not None and d.alternative.insee == "62743"


def test_ambiguous_name_reads_the_current_commune(ref: RefData) -> None:
    d = decompose("Sainte-Austreberthe", ref)
    assert d.insee == "76566" and d.candidates == ("76566",)
    assert d.historical is None
    assert d.alternative is not None and d.alternative.insee == "62743"


def test_department_picks_the_former_reading(ref: RefData) -> None:
    d = decompose("Sainte-Austreberthe, Pas-de-Calais", ref)
    assert d.insee == "62447"
    assert d.historical is not None and d.historical.insee == "62743"
    assert d.alternative is None


def test_codes_are_segments_too(ref: RefData) -> None:
    d = decompose("Roubaix 59100", ref)
    assert [(s.text, s.element.kind if s.element else None) for s in d.segments] == [
        ("Roubaix", "commune"),
        ("59100", "postal_code"),
    ]
