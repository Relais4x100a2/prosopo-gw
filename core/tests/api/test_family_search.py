"""Recherche textuelle dans les familles (noms des conjoints, lieu du mariage).

Base synthétique uniquement (noms fictifs).
"""

import pytest

from geneweb_py.api.models.family import FamilySearchSchema
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """\
fam DUPONT Jean_Pierre + #mp Saint-Étienne MARTIN Marie

fam BERNARD Louis + LEFÈVRE Hélène

fam MARTIN Paul + DURAND Zoé
"""


@pytest.fixture
def service():
    return GenealogyService(GeneWebParser().parse_string(GW))


def _search(service, query):
    params = FamilySearchSchema(page=1, size=50, query=query)
    families, total = service.search_families(params)
    return total, families


def test_query_matches_either_spouse(service):
    total, _ = _search(service, "martin")
    assert total == 2


def test_query_words_combine_both_spouses_any_order(service):
    total, families = _search(service, "marie dupont")
    assert total == 1
    assert families[0].husband_id is not None


def test_query_ignores_accents_and_matches_marriage_place(service):
    assert _search(service, "lefevre")[0] == 1
    assert _search(service, "saint etienne")[0] == 1


def test_no_query_returns_all(service):
    assert _search(service, None)[0] == 3
    assert _search(service, "inconnu")[0] == 0
