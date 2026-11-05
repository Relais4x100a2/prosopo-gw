"""Candidats organisations : index, routes liste / détail / reste à classer."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.services import genealogy_service as service_module
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.api.services.organization_candidates import build_candidate_index
from geneweb_py.api.services.organization_exports import (
    CANDIDATES_CSV_HEADER,
)
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


EMPTY_GW = """fam DUPONT Jean + MARTIN Marie
"""


def _rows(response):
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))


def test_org_json_export_contains_only_candidates(client):
    r = client.get("/api/v1/genealogy/export/org-json")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("application/json")
    assert 'filename="genealogie.org.json"' in r.headers["content-disposition"]
    body = r.json()
    assert body["version"] == 1
    ids = {o["id"] for o in body["organizations"]}
    assert "usine_martin_roubaix" in ids
    assert "comite_des_fetes_nord" not in ids
    assert body["links"]
    assert {link["organization_id"] for link in body["links"]} <= ids


def test_candidates_csv_header_and_rows(client):
    r = client.get("/api/v1/genealogy/export/organizations-csv")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="organisations.csv"' in r.headers["content-disposition"]
    rows = _rows(r)
    assert rows[0] == (
        "id;nom;type;lieu;source_du_nom;sources;mot_declencheur;confiance;a_revoir;"
        "collectif;nb_personnes;nb_evenements;premiere_annee;derniere_annee;lieux;roles"
    ).split(";")
    assert rows[0] == CANDIDATES_CSV_HEADER
    usine = next(r for r in rows if r[0] == "usine_martin_roubaix")
    assert usine[1] == "Usine Martin" and usine[9] == "oui" and usine[10] == "2"
    assert usine[5] == "occu|oth" and usine[12] == "1895" and usine[13] == "1902"
    assert usine[8] in ("oui", "non")


def test_links_csv_header_and_readable_names(client):
    r = client.get("/api/v1/genealogy/export/organization-links-csv")
    assert r.status_code == 200
    assert 'filename="liens_organisations.csv"' in r.headers["content-disposition"]
    rows = _rows(r)
    assert rows[0] == (
        "organisation_id;organisation;personne_id;personne;role;date;lieu;"
        "type_evenement;evenement;nb_temoins;statut;nom_retenu"
    ).split(";")
    row = next(
        r for r in rows if r[2] == "DUPONT_Jean_0" and r[0] == "usine_martin_roubaix"
    )
    assert row[3] == "DUPONT Jean" and row[7] == "occu" and row[8] == "Contremaître"
    assert row[9] == "3"
    assert row[10] == "" and row[11] == ""
    cercle = next(r for r in rows if r[0] == "cercle_philatelique")
    assert cercle[8] == "Cercle Philatelique"


def test_csv_exports_without_candidates_have_header_only():
    service = GenealogyService(GeneWebParser().parse_string(EMPTY_GW))
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        c = TestClient(app)
        r = c.get("/api/v1/genealogy/export/organizations-csv")
        assert r.status_code == 200
        assert _rows(r) == [CANDIDATES_CSV_HEADER]
        r = c.get("/api/v1/genealogy/export/organization-links-csv")
        assert r.status_code == 200 and len(_rows(r)) == 1
        body = c.get("/api/v1/genealogy/export/org-json").json()
        assert body["organizations"] == [] and body["links"] == []
    finally:
        app.dependency_overrides.clear()


def test_unknown_export_format_still_rejected(client):
    assert client.get("/api/v1/genealogy/export/org-xml").status_code in (400, 404, 422)
