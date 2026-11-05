"""Mots d'état civil, adresses et signal fort des tags (expériences partagées).

Fixtures 100 % synthétiques.
"""

import pytest

from geneweb_py.core.event import Event, EventType
from geneweb_py.core.event_to_organization import (
    EventToOrganizationMapper,
    _fold,
    address_in,
    is_civil_status,
)


def _other(tag, place=None):
    return Event(event_type=EventType.OTHER, event_type_raw=tag, place=place)


def _propose(tag, place=None, count=2):
    # clé de comptage : nom d'organisation replié, comme dans l'index
    key = _fold(tag.replace("_", " "))
    return EventToOrganizationMapper().propose(_other(tag, place), {key: count})


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("Mariage", True),
        ("Reconnaissance_enfant", True),
        ("Contrat_de_mariage", True),
        ("Publication_des_bans", True),
        ("Deces", True),
        ("Décès", True),
        ("Contrat_Engagement", False),
        ("Publication_ouvrage", False),
        ("Deportation", False),
        (None, False),
    ],
)
def test_is_civil_status(tag, expected):
    assert is_civil_status(tag) is expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Passage_Fictif_7", True),
        ("7_passage_Fictif", True),
        ("12_bis_rue_Haute", True),
        ("passage Fictif, 7", True),
        ("Rue_du_14_Juillet_3", True),
        ("Rue_du_14_Juillet", False),
        ("Avenue_du_8_Mai", False),
        ("Avenue_du_8_Mai_1945", False),
        ("Place_du_11_Novembre", False),
        ("8_Mai_avenue", False),
        ("Cercle_Fictif_7", False),
        ("Rue_Haute", False),
        ("Passage_12345", False),
    ],
)
def test_address_in(text, expected):
    assert address_in(text) is expected


def test_address_tag_is_a_probable_organization():
    p = _propose("Passage_Fictif_7")
    assert p.named_from == "address"
    assert p.confidence == 0.7
    assert p.review_required is False


def test_address_in_complement():
    p = _propose("Habitant", "[7 passage Fictif] - Lille")
    assert p.named_from == "address"
    assert p.name == "7 passage Fictif"


def test_establishment_tag_without_prefix_is_strong():
    assert _propose("Ecole_Fictive").confidence == 0.8


def test_plain_tag_stays_weak():
    p = _propose("Philatelie_Locale")
    assert p.confidence == 0.5
    assert p.named_from == "tag"


def test_role_prefix_tag_is_not_an_address():
    assert _propose("Cours_anglais_1") is None


def test_role_prefix_with_street_word_is_not_an_address():
    assert _propose("Cours_place_3") is None


def test_street_tag_with_year_stays_an_address():
    """Décision documentée : « Rue_Haute_1945 » (année en fin) reste une adresse."""
    p = _propose("Rue_Haute_1945")
    assert p is not None and p.named_from == "address"
