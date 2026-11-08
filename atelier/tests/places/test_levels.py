"""Tests du modèle de niveaux de lieux."""

from __future__ import annotations

import pytest

from prosopo_gw_atelier.places.levels import (
    FOREIGN_TYPES,
    FRENCH_TYPES,
    TYPE_LABELS,
    TYPE_PATTERN,
    Level,
    chain_label,
    check_chain,
    french_view,
    validated,
    view_origins,
)

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
    assert all(TYPE_PATTERN.match(t) for t in TYPE_LABELS)
