"""Agrégats des graphiques de l'onglet Stats : décennies, patronymes, couverture.

Base synthétique uniquement (noms fictifs).
"""

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """\
fam DUPONT Jean_Pierre 1901 #bp Paris MARTIN Marie 1909
beg
- h Paul 1925 #bp Paris #bs Registre_A
- f Zoe 1929
- h Luc
end

fam BERNARD Louis 1932 + DUPONT Anne 1934
"""


@pytest.fixture
def adv():
    service = GenealogyService(GeneWebParser().parse_string(GW))
    return service.get_stats()["advanced"]


def test_births_by_decade_counts_dated_persons_only(adv):
    assert adv["births_by_decade"] == {"1900": 2, "1920": 2, "1930": 2}
    # Ordre chronologique (l'histogramme se dessine tel quel).
    assert list(adv["births_by_decade"]) == ["1900", "1920", "1930"]


def test_top_surnames_sorted_by_count(adv):
    assert adv["top_surnames"][0] == {"surname": "DUPONT", "count": 5}
    counts = [row["count"] for row in adv["top_surnames"]]
    assert counts == sorted(counts, reverse=True)


def test_coverage_counts(adv):
    cov = adv["coverage"]
    assert cov["persons"] == 7
    assert cov["with_birth_date"] == 6
    assert cov["with_birth_place"] == 2
    assert cov["with_source"] == 1


def test_stats_endpoint_exposes_chart_aggregates():
    service = GenealogyService(GeneWebParser().parse_string(GW))
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        r = TestClient(app).get("/api/v1/genealogy/stats")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    advanced = r.json()["data"]["advanced"]
    for key in ("births_by_decade", "top_surnames", "coverage"):
        assert key in advanced
