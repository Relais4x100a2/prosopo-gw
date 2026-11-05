"""Candidats organisations : index, routes liste / détail / reste à classer."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.models.event import EventUpdateSchema
from geneweb_py.api.models.person import PersonUpdateSchema
from geneweb_py.api.serialization import stable_event_id
from geneweb_py.api.services import genealogy_service as service_module
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.api.services.organization_candidates import build_candidate_index
from geneweb_py.api.services.organization_exports import (
    CANDIDATES_CSV_HEADER,
)
from geneweb_py.core.event import EventType
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
#Societe_Histoire 1911
#Comite_des_fetes_Est 1920
end pevt

pevt MARTIN Pierre
#Societe_Histoire 1912
#Comite_des_fetes_Ouest 1920
end pevt
"""


@pytest.fixture
def service():
    return GenealogyService(GeneWebParser().parse_string(GW))


@pytest.fixture
def client(service):
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _event_id(service, person_id, index):
    person = service.get_person(person_id)
    return stable_event_id(
        person.events[index], scope="person", scope_key=person.unique_id, index=index
    )


def _members(client, org_id):
    body = client.get(f"/api/v1/organizations/candidates/{org_id}").json()
    return {m["person_id"]: m for m in body["members"]}


def test_candidates_default_sort_by_persons(client):
    data = client.get("/api/v1/organizations/candidates").json()
    ids = [c["id"] for c in data["items"]]
    # Trois candidats à deux personnes : égalité départagée par le nom replié.
    assert ids == ["cercle_philatelique", "societe_histoire", "usine_martin_roubaix"]
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
    autres = next(g for g in u["groups"] if g["word"] == "autres")
    # Review Focus 1 : un tag à nombre unique ne forme pas de groupe.
    assert any(e["event_type_raw"] == "Membre_1900" for e in autres["events"])
    assert "1900" not in words


def test_index_is_computed_once_per_service(monkeypatch, service):
    calls = []
    real = service_module.build_candidate_index
    monkeypatch.setattr(
        service_module,
        "build_candidate_index",
        lambda g, words: calls.append(1) or real(g, words),
    )
    first = service.get_candidate_index()
    assert service.get_candidate_index() is first
    assert len(calls) == 1
    # Une écriture réelle invalide l'index, qui est alors recalculé.
    service.delete_event(_event_id(service, "DUPONT_Jean_0", 0))
    second = service.get_candidate_index()
    assert second is not first and len(calls) == 2
    assert "usine_martin_roubaix" not in second.candidates


def test_delete_event_keeps_members_on_the_right_events(client, service):
    assert "DUPONT_Jean_0" in _members(client, "usine_martin_roubaix")
    service.delete_event(_event_id(service, "DUPONT_Jean_0", 0))  # l'occu de Jean
    cercle = _members(client, "cercle_philatelique")
    assert cercle["DUPONT_Jean_0"]["date"] == "1900"
    assert cercle["DUPONT_Jean_0"]["place"] is None
    assert cercle["DUPONT_Jean_0"]["witness_count"] == 0
    assert cercle["MARTIN_Marie_0"]["date"] == "1905"
    # Le candidat Usine n'a plus qu'une personne : il disparaît.
    assert (
        client.get("/api/v1/organizations/candidates/usine_martin_roubaix").status_code
        == 404
    )
    u = client.get("/api/v1/organizations/unmatched").json()
    all_tags = {e["event_type_raw"] for g in u["groups"] for e in g["events"]}
    assert "Cercle_Philatelique" not in all_tags  # toujours rattaché au candidat
    assert "Membre_1900" in all_tags and "Reunion" in all_tags
    assert u["total"] == 7


def test_update_event_changing_type_changes_candidates(client, service):
    assert "cercle_philatelique" in {
        c["id"] for c in client.get("/api/v1/organizations/candidates").json()["items"]
    }
    service.update_event(
        _event_id(service, "MARTIN_Marie_0", 1),
        EventUpdateSchema(event_type=EventType.RESIDENCE),
    )
    ids = {
        c["id"] for c in client.get("/api/v1/organizations/candidates").json()["items"]
    }
    assert "cercle_philatelique" not in ids


def test_person_writes_refresh_candidates(client, service):
    service.update_person("DUPONT_Jean_0", PersonUpdateSchema(first_name="Jules"))
    names = {m["person_name"] for m in _members(client, "cercle_philatelique").values()}
    assert "DUPONT Jules" in names
    service.delete_person("DUPONT_Jean_0")
    # Usine n'a plus qu'une personne : plus de candidat.
    assert (
        client.get("/api/v1/organizations/candidates/usine_martin_roubaix").status_code
        == 404
    )
    ids = {
        c["id"] for c in client.get("/api/v1/organizations/candidates").json()["items"]
    }
    assert ids == {"societe_histoire"}  # seul candidat encore à deux personnes
    assert all(
        link.person_id != "DUPONT_Jean_0"
        for link in service.genealogy.organization_links
    )


def test_unmatched_ignores_numeric_tokens():
    gw = """pevt DUPONT Jean
#Membre_1900 1900
#Annee_1900 1901
end pevt

pevt MARTIN Marie
#Membre_1900 1902
end pevt
"""
    idx = build_candidate_index(GeneWebParser().parse_string(gw))
    words = {g.word for g in idx.unmatched_groups}
    assert "1900" not in words and "membre" in words
    assert idx.unmatched_total == 3


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
    assert (
        usine[5] == "profession|événement libre"
        and usine[12] == "1895"
        and usine[13] == "1902"
    )
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
    assert (
        row[3] == "DUPONT Jean" and row[7] == "profession" and row[8] == "Contremaître"
    )
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


INJECTION_GW = """fam DUPONT Jean + MARTIN Marie
beg
end

pevt DUPONT Jean
#occu 1895
note ouvrier chez =1+1
#occu 1896
note ouvrier chez =1+1
end pevt

pevt MARTIN Marie
#occu 1897
note ouvrier chez =1+1
end pevt
"""


def test_csv_neutralises_formula_cells_but_not_numbers():
    from geneweb_py.api.services.organization_exports import candidates_csv, links_csv

    index = GenealogyService(
        GeneWebParser().parse_string(INJECTION_GW)
    ).get_candidate_index()
    for text in (candidates_csv(index), links_csv(index)):
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
        assert rows[1][1] == "'=1+1"
    cand = list(
        csv.reader(io.StringIO(candidates_csv(index).lstrip("\ufeff")), delimiter=";")
    )[1]
    assert cand[10] == "2" and cand[12] == "1895"  # colonnes numériques intactes


def test_csv_special_characters_round_trip():
    from geneweb_py.api.services.organization_exports import _render, _text

    cells = ["a;b", 'dit "oui"', "ligne1\nligne2", "-x", "@y", "\tz", "+1", "ok"]
    text = _render(["h"] * len(cells), [[_text(c) for c in cells]])
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
    assert rows[1] == [
        "a;b",
        'dit "oui"',
        "ligne1\nligne2",
        "'-x",
        "'@y",
        "'\tz",
        "'+1",
        "ok",
    ]
