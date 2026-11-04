"""Recherche de personnes par mots (nom + prénom, ordre libre, accents ignorés)."""

import pytest

from geneweb_py.api.models.person import PersonSearchSchema
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """\
fam DUPONT Jean_Pierre_Marie +1900 MARTIN Éloïse
beg
- h Paul 1925
end

fam DUPONT Luc +1950 LEROY Anne
"""


@pytest.fixture
def service() -> GenealogyService:
    return GenealogyService(GeneWebParser().parse_string(GW))


def _names(service, query):
    persons, _ = service.search_persons(PersonSearchSchema(query=query))
    return {(p.last_name, p.first_name) for p in persons}


@pytest.mark.parametrize(
    "query",
    [
        "DUPONT Jean",
        "Jean DUPONT",
        "dupont, jean",
        "DUPONT Pierre",
        "jean_pierre dupont",
    ],
)
def test_surname_and_first_name_in_any_order(service, query):
    assert ("DUPONT", "Jean_Pierre_Marie") in _names(service, query)
    assert ("DUPONT", "Luc") not in _names(service, query)


def test_single_word_still_matches_either_field(service):
    assert {("DUPONT", "Luc"), ("DUPONT", "Paul")} <= _names(service, "dupont")
    assert ("DUPONT", "Luc") in _names(service, "luc")


def test_accents_ignored(service):
    assert ("MARTIN", "Éloïse") in _names(service, "eloise martin")


def test_unmatched_word_excludes(service):
    assert _names(service, "DUPONT Inconnu") == set()
