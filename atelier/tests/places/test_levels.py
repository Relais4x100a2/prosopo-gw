"""Tests du modèle de niveaux de lieux."""

from __future__ import annotations

from pathlib import Path

import pytest

from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.levels import (
    FOREIGN_TYPES,
    FRENCH_TYPES,
    TYPE_LABELS,
    TYPE_PATTERN,
    Level,
    alternative_levels,
    chain_label,
    check_chain,
    french_view,
    rule_levels,
    validated,
    view_origins,
    written_postal_code,
)
from prosopo_gw_atelier.refdata import RefData, load_refdata

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "refdata_mini"


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(MINI)


MARCONNE = (
    Level(
        0,
        "Marconne",
        type="commune_historique",
        identifier="62549",
        end="2025-01-01",
        nature="deleguee",
        origin="insee",
        source="COG 2026",
    ),
    Level(
        1,
        "Hesdin-la-Forêt",
        type="commune",
        identifier="62447",
        origin="insee",
        source="COG 2026",
    ),
    Level(
        2,
        "Pas-de-Calais",
        type="departement",
        identifier="62",
        origin="insee",
        source="COG 2026",
    ),
    Level(3, "Hauts-de-France", type="region", origin="insee", source="COG 2026"),
    Level(4, "France", type="pays", origin="written"),
)


def test_french_view_of_historical_commune() -> None:
    assert french_view(MARCONNE, "62140") == {
        "commune": "Hesdin-la-Forêt",
        "insee_code": "62447",
        "postal_code": "62140",
        "department": "62",
        "region": "Hauts-de-France",
        "country": "France",
        "historical_commune": "Marconne",
        "historical_insee": "62549",
    }


def test_french_view_ignores_proposals() -> None:
    chain = (
        Level(0, "Lille", type="commune", identifier="59350"),
        Level(1, "Lomme", type="commune_historique", status="proposed"),
    )
    assert "historical_commune" not in french_view(chain, None)


def test_view_origins() -> None:
    assert view_origins(MARCONNE)["country"] == "written"
    assert view_origins(MARCONNE)["commune"] == "insee"
    assert "postal_code" not in view_origins(MARCONNE)


def test_chain_label() -> None:
    assert (
        chain_label(MARCONNE)
        == "Marconne, Hesdin-la-Forêt, Pas-de-Calais, Hauts-de-France, France"
    )


def test_validated_renumbers() -> None:
    chain = (Level(0, "A", status="proposed"), Level(1, "B"), Level(2, "C"))
    assert [(lv.rank, lv.name) for lv in validated(chain)] == [(0, "B"), (1, "C")]


@pytest.mark.parametrize(
    "chain, message",
    [
        ((), "au moins un niveau"),
        ((Level(0, " "),), "nom"),
        ((Level(0, "A", type="Comté"),), "type"),
        ((Level(0, "A", type="commune\n"),), "type"),
        ((Level(1, "A"),), "rang"),
        ((Level(0, "A", latitude=91.0),), "latitude"),
        ((Level(0, "A", longitude=181.0),), "longitude"),
    ],
)
def test_check_chain_rejects(chain: tuple[Level, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_chain(chain)


def test_check_chain_accepts_valid_chain() -> None:
    check_chain(MARCONNE)


def test_every_listed_type_has_a_label() -> None:
    assert set(TYPE_LABELS) == set(FRENCH_TYPES) | set(FOREIGN_TYPES)
    assert all(TYPE_PATTERN.fullmatch(t) for t in TYPE_LABELS)


def test_french_view_falls_back_to_old_region() -> None:
    chain = (
        Level(0, "Roubaix", type="commune", identifier="59512"),
        Level(1, "Nord-Pas-de-Calais", type="ancienne_region", origin="written"),
    )
    assert french_view(chain, None)["region"] == "Nord-Pas-de-Calais"


def test_french_view_uses_department_name_without_identifier() -> None:
    chain = (Level(0, "Nord", type="departement", origin="written"),)
    assert french_view(chain, None) == {"department": "Nord"}


def test_french_view_omits_empty_postal_code() -> None:
    chain = (Level(0, "Lille", type="commune", identifier="59350"),)
    assert "postal_code" not in french_view(chain, "")


def _names(chain: tuple[Level, ...]) -> list[tuple[str, str | None]]:
    return [(lv.name, lv.type) for lv in chain]


def test_winnipeg_keeps_manitoba(ref: RefData) -> None:
    chain = rule_levels(decompose("Winnipeg, , , Manitoba, Canada", ref), ref)
    assert _names(chain) == [
        ("Winnipeg", None),
        ("Manitoba", None),
        ("Canada", "pays"),
    ]
    assert [lv.rank for lv in chain] == [0, 1, 2]


def test_storrington_keeps_four_levels(ref: RefData) -> None:
    chain = rule_levels(
        decompose("Storrington, , East Sussex, England, Royaume-Uni", ref), ref
    )
    assert [lv.name for lv in chain] == [
        "Storrington",
        "East Sussex",
        "England",
        "Royaume-Uni",
    ]
    assert all(lv.origin == "written" for lv in chain)


def test_marconne_chain(ref: RefData) -> None:
    chain = rule_levels(decompose("Marconne, Pas-de-Calais", ref), ref)
    assert _names(chain) == [
        ("Marconne", "commune_historique"),
        ("Hesdin-la-Forêt", "commune"),
        ("Pas-de-Calais", "departement"),
        ("Hauts-de-France", "region"),
        ("France", "pays"),
    ]
    assert (
        chain[0].identifier == "62549"
        and chain[0].end == "2025-01-01"
        and chain[0].nature == "deleguee"
    )
    assert chain[1].source == "COG 2026"
    check_chain(chain)


def test_resolved_chain_origins_and_sources(ref: RefData) -> None:
    chain = rule_levels(decompose("Marconne, Pas-de-Calais", ref), ref)
    assert [lv.origin for lv in chain] == ["insee"] * 5
    assert all(lv.source == "COG 2026" for lv in chain)
    assert chain[2].identifier == "62"
    assert all(lv.status == "validated" for lv in chain)


def test_written_country_keeps_written_origin(ref: RefData) -> None:
    chain = rule_levels(decompose("ROUBAIX, Nord, France", ref), ref)
    assert chain[0].written == "ROUBAIX"
    assert chain[-1].type == "pays"
    assert chain[-1].origin == "written" and chain[-1].source is None


def test_rename_kept_as_written_name(ref: RefData) -> None:
    chain = rule_levels(decompose("Saint-Omer-en-Artois", ref), ref)
    assert chain[0].name == "Saint-Omer" and chain[0].written == "Saint-Omer-en-Artois"
    assert chain[0].type == "commune"


def test_unrecognised_segment_before_commune(ref: RefData) -> None:
    chain = rule_levels(decompose("La Motte, Roubaix, Nord", ref), ref)
    assert _names(chain)[:2] == [("La Motte", None), ("Roubaix", "commune")]


def test_unrecognised_segment_written_before_commune_after_department(
    ref: RefData,
) -> None:
    chain = rule_levels(decompose("Nord, La Motte, Roubaix", ref), ref)
    assert _names(chain) == [
        ("La Motte", None),
        ("Roubaix", "commune"),
        ("Nord", "departement"),
        ("Hauts-de-France", "region"),
        ("France", "pays"),
    ]


def test_commune_read_from_its_code_only(ref: RefData) -> None:
    chain = rule_levels(decompose("La Motte, Nord, Flandre, 59512", ref), ref)
    assert _names(chain) == [
        ("La Motte", None),
        ("Roubaix", "commune"),
        ("Nord", "departement"),
        ("Flandre", None),
        ("Hauts-de-France", "region"),
        ("France", "pays"),
    ]


def test_unrecognised_segment_after_its_recognised_level(ref: RefData) -> None:
    chain = rule_levels(decompose("Roubaix, Nord, Flandre, France", ref), ref)
    assert _names(chain) == [
        ("Roubaix", "commune"),
        ("Nord", "departement"),
        ("Flandre", None),
        ("Hauts-de-France", "region"),
        ("France", "pays"),
    ]
    assert chain[2].origin == "written"


def test_codes_are_not_levels(ref: RefData) -> None:
    decomposition = decompose("Roubaix, 59100, 59512", ref)
    chain = rule_levels(decomposition, ref)
    assert [lv.name for lv in chain][:1] == ["Roubaix"]
    assert not any(lv.name.isdigit() for lv in chain)
    assert written_postal_code(decomposition) == "59100"
    assert written_postal_code(decompose("Roubaix", ref)) is None


def test_old_region_is_kept(ref: RefData) -> None:
    chain = rule_levels(decompose("Roubaix, Nord-Pas-de-Calais", ref), ref)
    assert ("Nord-Pas-de-Calais", "ancienne_region") in _names(chain)
    assert ("Hauts-de-France", "region") in _names(chain)


def test_historical_country_stays_as_written(ref: RefData) -> None:
    chain = rule_levels(decompose("Königsberg, Prusse", ref), ref)
    assert _names(chain) == [("Königsberg", None), ("Prusse", None)]


def test_unresolved_writing_normalises_known_levels(ref: RefData) -> None:
    chain = rule_levels(decompose("Ailleurs, 62, Royaume de Belgique", ref), ref)
    assert _names(chain) == [
        ("Ailleurs", None),
        ("Pas-de-Calais", "departement"),
        ("Belgique", "pays"),
    ]
    assert chain[1].identifier == "62" and chain[1].written == "62"
    assert chain[1].origin == "rule"
    assert chain[2].written == "Royaume de Belgique" and chain[2].origin == "rule"
    assert chain[0].origin == "written" and chain[0].written is None


def test_alternative_levels(ref: RefData) -> None:
    alt = alternative_levels(decompose("Sainte-Austreberthe", ref), ref)
    assert (
        alt is not None
        and alt[0].type == "commune_historique"
        and alt[1].name == "Hesdin-la-Forêt"
    )
    assert alt[0].identifier == "62743" and alt[0].nature == "deleguee"
    chain = rule_levels(decompose("Sainte-Austreberthe", ref), ref)
    assert _names(chain)[:2] == [
        ("Sainte-Austreberthe", "commune"),
        ("Seine-Maritime", "departement"),
    ]
    assert alternative_levels(decompose("Roubaix", ref), ref) is None


@pytest.mark.parametrize(
    "writing",
    [", , , ,", ",", "-", " ; ( ) ", "A, B, C, D, E, F, G, H, I, J, K, L"],
)
def test_empty_and_degenerate_writings(ref: RefData, writing: str) -> None:
    chain = rule_levels(decompose(writing, ref), ref)
    assert all(lv.name.strip() for lv in chain)
    assert [lv.rank for lv in chain] == list(range(len(chain)))
