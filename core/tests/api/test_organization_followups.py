"""Suites des organisations candidates : mots ignorés, CSV lisible par Excel français."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.api.services.organization_candidates import (
    DEFAULT_IGNORED_WORDS,
    build_candidate_index,
)
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """pevt DUPONT Jean
#Atelier_Couture 1906 #p Lille
#Cercle_Philatelique 1900
#educ 1880 #p [Ecole_Saint_Paul]_-_Lille
end pevt

pevt MARTIN Marie
#Atelier_Couture 1906 #p Lille
#Cercle_Philatelique 1905
#Bureau_Rue_Haute 1910
#educ 1882 #p [Ecole_Saint_Paul]_-_Lille
end pevt

pevt DURAND Paul
#Atelier_Couture 1906 #p Lille
#Bureau_Rue_Basse 1911
end pevt
"""


def _genealogy():
    return GeneWebParser().parse_string(GW)


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


def _names(index):
    return {c.name for c in index.candidates.values()}


def _unmatched_tags(index):
    return {e.event_type_raw for g in index.unmatched_groups for e in g.events}


def _rows(text):
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:]), delimiter=";"))


# --- Mots ignorés -----------------------------------------------------------


def test_default_ignored_words():
    assert DEFAULT_IGNORED_WORDS == ()


def test_without_ignored_words_census_is_a_candidate():
    index = build_candidate_index(_genealogy(), ignored_words=())
    assert any("Atelier" in name for name in _names(index))
    assert index.ignored_total == 0


def test_ignored_words_drop_atelier_and_bureau():
    index = build_candidate_index(_genealogy(), ignored_words=("atelier", "bureau"))
    assert not any("Atelier" in name for name in _names(index))
    assert "Cercle_Philatelique" in {n.replace(" ", "_") for n in _names(index)}
    tags = _unmatched_tags(index)
    assert not any(t.startswith(("Atelier", "Bureau")) for t in tags)
    assert index.ignored_total == 5  # 3 ateliers + 2 bureaus


def test_ignored_word_matching_is_folded_and_whole_word():
    index = build_candidate_index(_genealogy(), ignored_words=("ATELIER",))
    assert not any("Atelier" in name for name in _names(index))
    # « bureau » n'est plus ignoré : ses événements reviennent à classer.
    assert any(t.startswith("Bureau") for t in _unmatched_tags(index))
    # Un mot partiel n'ignore rien.
    partial = build_candidate_index(_genealogy(), ignored_words=("recens",))
    assert any("Atelier" in name for name in _names(partial))


def test_ignored_words_only_apply_to_free_events():
    # « ecole » ignoré ne retire pas l'école issue d'un événement typé.
    index = build_candidate_index(_genealogy(), ignored_words=("ecole",))
    assert any("Saint Paul" in n.replace("_", " ") for n in _names(index))


def test_ignored_words_api_roundtrip(client):
    body = client.get("/api/v1/organizations/ignored-words").json()
    assert body == {"words": []}

    res = client.put(
        "/api/v1/organizations/ignored-words",
        json={"words": ["Atelier", " cercle ", "atelier", ""]},
    )
    assert res.status_code == 200
    assert res.json() == {"words": ["atelier", "cercle"]}

    names = {
        c["name"]
        for c in client.get("/api/v1/organizations/candidates").json()["items"]
    }
    assert not any("Philatelique" in n for n in names)
    unmatched = client.get("/api/v1/organizations/unmatched").json()
    assert unmatched["ignored_total"] == 5  # 3 ateliers + 2 cercles
    tags = {e["event_type_raw"] for g in unmatched["groups"] for e in g["events"]}
    assert any(t.startswith("Bureau") for t in tags)


def test_ignored_words_api_rejects_bad_input(client):
    url = "/api/v1/organizations/ignored-words"
    assert client.put(url, json={"words": ["x" * 41]}).status_code == 422
    many = [
        "mot" + "abcdefghijklmnopqrstuvwxyz"[i // 26] + chr(97 + i % 26)
        for i in range(51)
    ]
    assert client.put(url, json={"words": many}).status_code == 422
    assert client.put(url, json={"words": ["a"] * 51}).json() == {"words": ["a"]}
    assert client.put(url, json={"words": ["=1+1"]}).status_code == 422


def test_ignored_words_apply_to_exports(client):
    client.put("/api/v1/organizations/ignored-words", json={"words": []})
    text = client.get("/api/v1/genealogy/export/organizations-csv").text
    assert "Atelier" in text
    client.put("/api/v1/organizations/ignored-words", json={"words": ["atelier"]})
    text = client.get("/api/v1/genealogy/export/organizations-csv").text
    assert "Atelier" not in text
    org_json = client.get("/api/v1/genealogy/export/org-json").json()
    assert not any("Atelier" in o["name"] for o in org_json["organizations"])


# --- CSV lisible dans un Excel français --------------------------------------


def test_candidates_csv_is_french_and_sorted(client):
    rows = _rows(client.get("/api/v1/genealogy/export/organizations-csv").text)
    header, body = rows[0], rows[1:]
    col = {name: i for i, name in enumerate(header)}
    names = [r[col["nom"]] for r in body]
    assert names == sorted(names, key=str.casefold)
    by_name = {r[col["nom"]]: r for r in body}
    school = next(r for n, r in by_name.items() if "Saint" in n)
    assert school[col["type"]] == "École"
    assert school[col["source_du_nom"]] == "Événement typé"
    assert school[col["sources"]] == "éducation"
    assert "," in school[col["confiance"]] and "." not in school[col["confiance"]]
    circle = next(r for n, r in by_name.items() if "Philatelique" in n)
    assert circle[col["source_du_nom"]] == "Nom personnalisé"
    assert circle[col["sources"]] == "événement libre"


def test_links_csv_is_french_and_sorted(client):
    rows = _rows(client.get("/api/v1/genealogy/export/organization-links-csv").text)
    header, body = rows[0], rows[1:]
    col = {name: i for i, name in enumerate(header)}
    keys = [
        (r[col["organisation"]].casefold(), r[col["personne"]].casefold()) for r in body
    ]
    assert keys == sorted(keys)
    assert {r[col["type_evenement"]] for r in body} == {"éducation", "événement libre"}


# --- État conservé d'une requête à l'autre (session réelle) ------------------


@pytest.fixture
def session_client():
    from geneweb_py.api.main import create_app

    with TestClient(create_app()) as c:
        res = c.post(
            "/api/v1/sessions",
            files={"file": ("demo.gw", GW.encode(), "application/octet-stream")},
        )
        assert res.status_code == 201
        c.headers["X-Session-Token"] = res.json()["session_token"]
        yield c


def test_ignored_words_persist_across_requests(session_client):
    url = "/api/v1/organizations/ignored-words"
    assert session_client.put(url, json={"words": ["atelier"]}).status_code == 200
    assert session_client.get(url).json() == {"words": ["atelier"]}
    unmatched = session_client.get("/api/v1/organizations/unmatched").json()
    assert unmatched["ignored_total"] == 3
    assert {g["word"] for g in unmatched["groups"]} >= {"bureau"}


def test_candidate_index_is_cached_across_requests(session_client, monkeypatch):
    import geneweb_py.api.services.genealogy_service as gs

    calls = []
    real = gs.build_candidate_index
    monkeypatch.setattr(
        gs, "build_candidate_index", lambda g, words: calls.append(1) or real(g, words)
    )
    session_client.get("/api/v1/organizations/candidates")
    session_client.get("/api/v1/organizations/unmatched")
    assert len(calls) == 1


def test_api_write_refreshes_candidates_in_real_session(session_client):
    def names():
        items = session_client.get("/api/v1/organizations/candidates").json()["items"]
        return {c["name"] for c in items}

    assert any("Philatelique" in n for n in names())
    assert session_client.delete("/api/v1/persons/MARTIN_Marie_0").status_code == 200
    # Le cercle et l'école n'ont plus qu'une personne : seul l'atelier reste.
    assert names() == {"Atelier Couture"}
