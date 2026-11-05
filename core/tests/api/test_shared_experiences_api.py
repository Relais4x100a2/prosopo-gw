"""API des expériences proches : service, JSON, CSV, caches (fixtures synthétiques)."""

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app, create_app
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.api.services.organization_candidates import build_candidate_index
from geneweb_py.core.event_to_organization import event_ref
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """fam DUPONT Jean + MARTIN Marie
beg
end

pevt DUPONT Jean
#Deportation 1943 #p Lillebonne
#Philatelie_Locale 1905 #p Lillebonne
#Recensement 1936 #p Lillebonne
#Deportation <1940
end pevt

pevt MARTIN Marie
#Deportation 1943 #p Lillebonne
#Philatelie_Locale 1905 #p Lillebonne
end pevt

pevt DURAND Paul
#Voyage_Italie 1950 #p Valmont
end pevt
"""

CSV_HEADER = "experience;theme;periode;lieux;raison;personne;evenement;annee;lieu"


def _genealogy():
    return GeneWebParser(validate=False).parse_string(GW)


@pytest.fixture
def service():
    return GenealogyService(_genealogy())


@pytest.fixture
def client(service):
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _by_label(body, label):
    return [i for i in body["items"] if i["label"] == label]


def test_shared_experiences_total_counts_before_cap(client, monkeypatch):
    import geneweb_py.api.routers.organizations as orgs_router

    full = client.get("/api/v1/organizations/shared-experiences").json()
    assert full["total"] >= 2
    monkeypatch.setattr(orgs_router, "SHARED_EXPERIENCES_CAP", 1)
    body = client.get("/api/v1/organizations/shared-experiences").json()
    assert len(body["items"]) == 1
    assert body["total"] == full["total"]
    assert body["truncated"] is True


def test_shared_experiences_endpoint(client):
    r = client.get("/api/v1/organizations/shared-experiences")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(body["items"])
    assert body["civil_status_total"] >= 1
    assert body["undated_total"] == 1
    assert body["truncated"] is False
    (depo,) = _by_label(body, "Déportation")
    assert depo["person_count"] == 2
    assert depo["reasons"][0]["kind"] == "same_place"
    names = {p["person_name"] for p in depo["persons"]}
    assert names == {"DUPONT Jean", "MARTIN Marie"}
    first = depo["persons"][0]
    assert set(first) == {
        "person_id",
        "person_name",
        "event_type_raw",
        "label",
        "year_start",
        "year_end",
        "place",
    }
    assert first["year_start"] == 1943


def test_weak_tag_flows_to_shared_experiences(client, service):
    names = {c.name for c in service.get_candidate_index().candidates.values()}
    assert "Philatelie Locale" not in names
    body = client.get("/api/v1/organizations/shared-experiences").json()
    (exp,) = _by_label(body, "Philatelie Locale")
    assert exp["persons"][0]["label"] == "Philatelie Locale"
    assert exp["year_min"] == 1905


def test_shared_experiences_csv(client):
    r = client.get("/api/v1/genealogy/export/shared-experiences-csv")
    assert r.status_code == 200
    assert "experiences_proches.csv" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    lines = text[1:].splitlines()
    assert lines[0] == CSV_HEADER
    rows = list(csv.reader(io.StringIO(text[1:]), delimiter=";"))[1:]
    depo = [row for row in rows if row[1] == "Déportation"]
    assert [row[5] for row in depo] == ["DUPONT Jean", "MARTIN Marie"]
    assert depo[0][2] == "1943"
    assert depo[0][3] == "Lillebonne"
    assert depo[0][4] == "même lieu"
    assert depo[0][6] == "Deportation"
    assert depo[0][7] == "1943"
    assert depo[0][8].startswith("Lillebonne")
    assert len(rows) == 4  # 2 déportations + 2 philatélie
    assert all(len(row) == 9 for row in rows)


def test_csv_sorted_by_experience_then_folded_name():
    from geneweb_py.api.services.organization_exports import shared_experiences_csv

    g = GeneWebParser(validate=False).parse_string(
        "pevt MARTIN Zoe\n#Deportation 1943 #p Lillebonne\nend pevt\n\n"
        "pevt MARTIN Édith\n#Deportation 1943 #p Lillebonne\nend pevt\n"
    )
    from geneweb_py.core.shared_experiences import find_shared_experiences

    rows = list(
        csv.reader(
            io.StringIO(shared_experiences_csv(g, find_shared_experiences(g))[1:]),
            delimiter=";",
        )
    )[1:]
    assert [r[5] for r in rows] == ["MARTIN Édith", "MARTIN Zoe"]


def test_ignored_word_change_recomputes(client):
    url = "/api/v1/organizations/shared-experiences"
    assert _by_label(client.get(url).json(), "Déportation")
    r = client.put(
        "/api/v1/organizations/ignored-words", json={"words": ["deportation"]}
    )
    assert r.status_code == 200
    assert not _by_label(client.get(url).json(), "Déportation")


def test_sidecar_weak_orgs_filtered():
    from geneweb_py.core.organization import (
        Organization,
        OrganizationLink,
        OrganizationType,
    )

    g = _genealogy()
    org = Organization(
        id="org_weak", name="Faible", type=OrganizationType.OTHER, confidence=0.5
    )
    org.metadata["named_from"] = "tag"
    g.organizations["org_weak"] = org
    for pid, person in g.persons.items():
        for i, ev in enumerate(person.events):
            if ev.event_type_raw == "Deportation" and ev.date and ev.date.year == 1943:
                g.organization_links.append(
                    OrganizationLink(
                        person_id=pid,
                        organization_id="org_weak",
                        source_event_id=event_ref(pid, i),
                    )
                )
    assert len(g.organization_links) == 2
    assert "org_weak" not in build_candidate_index(g).candidates
    service = GenealogyService(g)
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        body = TestClient(app).get("/api/v1/organizations/shared-experiences").json()
    finally:
        app.dependency_overrides.clear()
    assert _by_label(body, "Déportation")


def test_cache_invalidated_after_write_real_session(tmp_path: Path):
    gw = tmp_path / "synthetic.gw"
    gw.write_text(GW, encoding="utf-8")
    with TestClient(create_app()) as c:
        with open(gw, "rb") as f:
            resp = c.post(
                "/api/v1/sessions",
                files={"file": ("synthetic.gw", f, "application/octet-stream")},
            )
        assert resp.status_code == 201
        headers = {"X-Session-Token": resp.json()["session_token"]}
        url = "/api/v1/organizations/shared-experiences"
        body = c.get(url, headers=headers).json()
        (depo,) = _by_label(body, "Déportation")
        pid = depo["persons"][0]["person_id"]
        events = c.get(f"/api/v1/persons/{pid}/events", headers=headers).json()["data"]
        target = next(
            e
            for e in events
            if e["custom_type"] == "Deportation" and e["date"] == "1943"
        )
        r = c.put(f"/api/v1/events/{target['id']}", json={"place": ""}, headers=headers)
        assert r.status_code == 200, r.text
        after = c.get(url, headers=headers).json()
        assert not _by_label(after, "Déportation")


def test_event_in_experience_is_absent_from_unmatched(client):
    body = client.get("/api/v1/organizations/unmatched").json()
    events = [e for g in body["groups"] for e in g["events"]]
    tags = {e["event_type_raw"] for e in events}
    assert "Philatelie_Locale" not in tags  # dans une expérience
    # Déportation 1943 (deux personnes) en expérience ; le « <1940 » non daté reste.
    depo = [e for e in events if e["event_type_raw"] == "Deportation"]
    assert [e["date"] for e in depo] == ["<1940"]
    assert "Voyage_Italie" in tags  # une seule personne : reste à classer
    assert body["total"] == len(
        {(e["person_id"], e["date"], e["event_type_raw"]) for e in events}
    )


def test_unmatched_recomputed_after_ignoring_word(client):
    before = client.get("/api/v1/organizations/unmatched").json()["total"]
    client.put("/api/v1/organizations/ignored-words", json={"words": ["voyage"]})
    after = client.get("/api/v1/organizations/unmatched").json()["total"]
    assert after == before - 1
