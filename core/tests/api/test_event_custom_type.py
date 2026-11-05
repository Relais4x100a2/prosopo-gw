"""Nom personnalisé des événements « Autre » et clés des stats par type."""

from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """fam DUPONT Jean 1901 + 1925 MARTIN Marie 1909
fevt
#marr 1925 #p Paris
#marc 1924 #p Paris
#Bénédiction_nuptiale 1925 #p Paris
end fevt

pevt DUPONT Jean
#birt 1901 #p Paris
#Capitaine_de_navire 1931 #p Brest
end pevt
"""


def _client() -> TestClient:
    service = GenealogyService(GeneWebParser().parse_string(GW))
    app.dependency_overrides[get_session_service] = lambda: service
    return TestClient(app)


def test_other_events_expose_custom_type_only_for_free_tags():
    try:
        items = _client().get("/api/v1/events/?size=100").json()["items"]
    finally:
        app.dependency_overrides.clear()
    by_type = {(i["event_type"], i["custom_type"]) for i in items}
    assert ("oth", "Capitaine_de_navire") in by_type
    assert ("other", "Bénédiction_nuptiale") in by_type
    # Types standards : pas de nom personnalisé.
    assert all(
        i["custom_type"] is None
        for i in items
        if i["event_type"] in ("birt", "marr", "marc")
    )


def test_stats_count_family_events_with_their_family_type():
    try:
        stats = _client().get("/api/v1/genealogy/stats").json()["data"]
    finally:
        app.dependency_overrides.clear()
    by_type = stats["events_by_type"]
    # Mêmes clés que le filtre de l'onglet Événements : plus de « oth » fourre-tout.
    assert by_type["marc"] == 1
    assert by_type["other"] == 1
    assert by_type["oth"] == 1
