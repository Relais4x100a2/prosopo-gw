"""Résolution groupée des noms : une requête pour N personnes (anti N+1).

Base synthétique uniquement (noms fictifs).
"""

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.routers.persons import MAX_NAME_IDS
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """\
fam DUPONT Jean_Pierre 1900 MARTIN Marie
beg
- h Paul 1925
end
"""


@pytest.fixture
def client():
    service = GenealogyService(GeneWebParser().parse_string(GW))
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        yield TestClient(app), service
    finally:
        app.dependency_overrides.clear()


def _ids(service):
    return {p.first_name: p.unique_id for p in service.genealogy.persons.values()}


def test_returns_names_for_known_ids_only(client):
    c, service = client
    ids = _ids(service)
    r = c.get(
        "/api/v1/persons/names",
        params=[("ids", ids["Jean_Pierre"]), ("ids", ids["Paul"]), ("ids", "inconnu")],
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) == {ids["Jean_Pierre"], ids["Paul"]}
    assert data[ids["Jean_Pierre"]]["surname"] == "DUPONT"
    assert data[ids["Jean_Pierre"]]["first_name"] == "Jean_Pierre"
    assert "birth_date" in data[ids["Paul"]]


def test_route_not_swallowed_by_person_path(client):
    c, _ = client
    r = c.get("/api/v1/persons/names")
    assert r.status_code == 200
    assert r.json()["data"] == {}


def test_too_many_ids_rejected(client):
    c, _ = client
    r = c.get(
        "/api/v1/persons/names",
        params=[("ids", f"x{i}") for i in range(MAX_NAME_IDS + 1)],
    )
    assert r.status_code == 422
