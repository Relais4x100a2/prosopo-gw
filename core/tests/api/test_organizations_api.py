"""Candidats organisations : index, routes liste / détail / reste à classer."""

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.services import genealogy_service as service_module
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.api.services.organization_candidates import build_candidate_index
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """pevt DUPONT Jean
#occu 1895 #p [Usine_Martin]_-_Roubaix
wit m: MARTIN Marie
wit m: DURAND Paul
wit m: MARTIN Pierre
note Contremaître
#Cercle_Philatelique 1900
#Membre_1900 1900
#Comite_des_fetes_Nord 1920
end pevt

pevt MARTIN Marie
#Reunion 1902 #p [Usine_Martin]_-_Roubaix
#Cercle_Philatelique 1905
#Comite_des_fetes_Sud 1920
end pevt

pevt DURAND Paul
#Capitaine_de_navire 1890
#Conference_Histoire 1911
#Comite_des_fetes_Est 1920
end pevt

pevt MARTIN Pierre
#Conference_Histoire 1912
#Comite_des_fetes_Ouest 1920
end pevt
"""


@pytest.fixture
def client():
    service = GenealogyService(GeneWebParser().parse_string(GW))
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_candidates_default_sort_by_persons(client):
    data = client.get("/api/v1/organizations/candidates").json()
    ids = [c["id"] for c in data["items"]]
    # Trois candidats à deux personnes : égalité départagée par le nom replié.
    assert ids == ["cercle_philatelique", "conference_histoire", "usine_martin_roubaix"]
    assert not any(i.startswith("comite_des_fetes") for i in ids)  # une personne chacun
    first = next(c for c in data["items"] if c["id"] == "usine_martin_roubaix")
    assert first["collective"] is True and first["person_count"] == 2
    assert first["event_count"] == 2
    assert first["first_year"] == 1895 and first["last_year"] == 1902
    assert first["sources"] == ["occu", "oth"]
    assert first["named_from"] == "typed_event"
    assert data["pagination"]["total"] == len(ids)


def test_candidates_filters_and_sorts(client):
    items = client.get("/api/v1/organizations/candidates?type=association").json()[
        "items"
    ]
    assert items and all(c["type"] == "association" for c in items)
    names = [
        c["name"]
        for c in client.get("/api/v1/organizations/candidates?sort=name").json()[
            "items"
        ]
    ]
    assert names == sorted(names, key=str.casefold)
    r = client.get("/api/v1/organizations/candidates?q=philat").json()
    assert r["pagination"]["total"] == 1
    assert client.get("/api/v1/organizations/candidates?sort=bogus").status_code == 422


def test_candidates_period_sort_and_paging(client):
    body = client.get(
        "/api/v1/organizations/candidates?sort=period&size=1&page=2"
    ).json()
    assert len(body["items"]) == 1
    assert body["pagination"]["has_prev"] is True
    years = [
        c["first_year"]
        for c in client.get("/api/v1/organizations/candidates?sort=period").json()[
            "items"
        ]
    ]
    assert years == sorted(years)


def test_candidate_detail_lists_members(client):
    d = client.get("/api/v1/organizations/candidates/usine_martin_roubaix").json()
    m = next(x for x in d["members"] if x["person_id"] == "DUPONT_Jean_0")
    assert m == {
        "person_id": "DUPONT_Jean_0",
        "person_name": "DUPONT Jean",
        "role": "Contremaître",
        "date": "1895",
        "place": "[Usine Martin] - Roubaix",
        "source_event_type": "occu",
        "event_type_raw": "occu",
        "event_label": "Contremaître",
        "witness_count": 3,
        "year": 1895,
    }


def test_candidate_detail_unknown_id_is_404(client):
    assert client.get("/api/v1/organizations/candidates/nope").status_code == 404
    assert client.get("/api/v1/organizations/candidates/ecole%20x").status_code == 404


def test_unmatched_lists_other_events_without_candidate(client):
    u = client.get("/api/v1/organizations/unmatched").json()
    words = {g["word"]: g["count"] for g in u["groups"]}
    assert words["fetes"] == 4 and words["comite"] == 4
    assert u["groups"][-1]["word"] == "autres"
    assert all(len(g["events"]) <= 50 for g in u["groups"])
    assert u["total"] == 6


def test_index_is_computed_once_per_service(monkeypatch):
    calls = []
    real = service_module.build_candidate_index
    monkeypatch.setattr(
        service_module,
        "build_candidate_index",
        lambda g: calls.append(1) or real(g),
    )
    service = GenealogyService(GeneWebParser().parse_string(GW))
    first = service.get_candidate_index()
    assert service.get_candidate_index() is first
    assert len(calls) == 1
    service._candidate_index = None  # invalidation par une écriture
    service.get_candidate_index()
    assert len(calls) == 2


def test_index_tolerates_links_without_event_reference():
    g = GeneWebParser().parse_string(GW)
    g.infer_organizations()
    for link in g.organization_links:
        link.source_event_id = "pevt:ghost:9"
    idx = build_candidate_index(g)
    usine = idx.candidates["usine_martin_roubaix"]
    assert usine.sources == ["oth"]
    assert all(m.witness_count == 0 for m in usine.members)


def test_requires_session_token():
    with TestClient(app) as c:
        assert c.get("/api/v1/organizations/candidates").status_code in (
            401,
            403,
            422,
        )  # en-tête X-Session-Token absent
