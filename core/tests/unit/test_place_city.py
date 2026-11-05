"""Ville d'un lieu : texte avant la première virgule, complément [] exclu."""

from types import SimpleNamespace

import pytest

from geneweb_py.api.services.genealogy_service import (
    _distinct_places,
    _top_places_from_persons,
)
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.place import parse_place, place_city


@pytest.mark.parametrize(
    "raw, city",
    [
        ("Lille", "Lille"),
        ("Lille, Nord, France", "Lille"),
        ("[Maternité Sainte Anne] - Lille, Nord", "Lille"),
        ("[Atelier]_-_Roubaix,_Nord", "Roubaix"),
        ("  Paris ,France ", "Paris"),
        (", Nord", "Nord"),  # pas de ville avant la virgule : on garde le reste
        ("", None),
        (None, None),
    ],
)
def test_place_city(raw, city):
    assert place_city(raw) == city


def test_parsed_place_city_keeps_name():
    parsed = parse_place("[Usine] - Lille, Nord")
    assert parsed is not None
    assert parsed.name == "Lille, Nord" and parsed.city == "Lille"


def _persons(*places):
    return [SimpleNamespace(birth_place=p) for p in places]


def test_stats_count_places_by_city():
    persons = _persons(
        "Lille, Nord, France",
        "[Maternité] - Lille",
        "lille, Nord",
        "Roubaix",
        None,
        " ",
    )
    top = _top_places_from_persons(persons, "birth_place", limit=15)
    assert top == [{"place": "Lille", "count": 3}, {"place": "Roubaix", "count": 1}]
    assert _distinct_places(persons, "birth_place") == 2


def test_organizations_group_by_city():
    gw = """pevt DUPONT Jean
#Cercle_Philatelique 1900 #p Lille, Nord
end pevt

pevt MARTIN Marie
#Cercle_Philatelique 1905 #p Lille
end pevt
"""
    from geneweb_py.api.services.organization_candidates import build_candidate_index

    index = build_candidate_index(GeneWebParser().parse_string(gw))
    [candidate] = index.candidates.values()
    assert candidate.place == "Lille" and candidate.person_count == 2


def test_complement_with_inner_dash_stays_whole():
    from geneweb_py.core.place import parse_place

    for raw in (
        "[Rue_Fictive_-_Petit_seminaire]_-_Lyon,_Rhone",
        "[Rue Fictive - Petit seminaire] - Lyon, Rhone",
    ):
        parsed = parse_place(raw)
        assert parsed is not None
        assert parsed.complement in (
            "Rue_Fictive_-_Petit_seminaire",
            "Rue Fictive - Petit seminaire",
        )
        assert parsed.name == "Lyon,_Rhone" or parsed.name == "Lyon, Rhone"
        assert parsed.city == "Lyon"


def test_unclosed_bracket_falls_back_to_first_dash():
    from geneweb_py.core.place import parse_place

    parsed = parse_place("[Atelier_-_Lyon")
    assert parsed is not None and parsed.name == "Lyon"
