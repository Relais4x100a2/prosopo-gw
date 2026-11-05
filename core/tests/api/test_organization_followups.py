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
#Recensement 1906 #p Lille
#Cercle_Philatelique 1900
#educ 1880 #p [Ecole_Saint_Paul]_-_Lille
end pevt

pevt MARTIN Marie
#Recensement 1906 #p Lille
#Cercle_Philatelique 1905
#Domicile_Rue_Haute 1910
#educ 1882 #p [Ecole_Saint_Paul]_-_Lille
end pevt

pevt DURAND Paul
#Recensement 1906 #p Lille
#Domicile_Rue_Basse 1911
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
    assert DEFAULT_IGNORED_WORDS == ("recensement", "domicile")


def test_without_ignored_words_census_is_a_candidate():
    index = build_candidate_index(_genealogy(), ignored_words=())
    assert any("Recensement" in name for name in _names(index))
    assert index.ignored_total == 0


def test_default_ignored_words_drop_census_and_domicile():
    index = build_candidate_index(_genealogy())
    assert not any("Recensement" in name for name in _names(index))
    assert "Cercle_Philatelique" in {n.replace(" ", "_") for n in _names(index)}
    tags = _unmatched_tags(index)
    assert not any(t.startswith(("Recensement", "Domicile")) for t in tags)
    assert index.ignored_total == 5  # 3 recensements + 2 domiciles


def test_ignored_word_matching_is_folded_and_whole_word():
    index = build_candidate_index(_genealogy(), ignored_words=("RECENSÉMENT",))
    assert not any("Recensement" in name for name in _names(index))
    # « domicile » n'est plus ignoré : ses événements reviennent à classer.
    assert any(t.startswith("Domicile") for t in _unmatched_tags(index))
    # Un mot partiel n'ignore rien.
    partial = build_candidate_index(_genealogy(), ignored_words=("recens",))
    assert any("Recensement" in name for name in _names(partial))


def test_ignored_words_only_apply_to_free_events():
    # « ecole » ignoré ne retire pas l'école issue d'un événement typé.
    index = build_candidate_index(_genealogy(), ignored_words=("ecole",))
    assert any("Saint Paul" in n.replace("_", " ") for n in _names(index))


def test_ignored_words_api_roundtrip(client):
    body = client.get("/api/v1/organizations/ignored-words").json()
    assert body == {"words": ["recensement", "domicile"]}

    res = client.put(
        "/api/v1/organizations/ignored-words",
        json={"words": ["Recensement", " cercle ", "recensement", ""]},
    )
    assert res.status_code == 200
    assert res.json() == {"words": ["recensement", "cercle"]}

    names = {
        c["name"]
        for c in client.get("/api/v1/organizations/candidates").json()["items"]
    }
    assert not any("Philatelique" in n for n in names)
    unmatched = client.get("/api/v1/organizations/unmatched").json()
    assert unmatched["ignored_total"] == 5  # 3 recensements + 2 cercles
    tags = {e["event_type_raw"] for g in unmatched["groups"] for e in g["events"]}
    assert any(t.startswith("Domicile") for t in tags)


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
    assert "Recensement" in text
    client.put("/api/v1/organizations/ignored-words", json={"words": ["recensement"]})
    text = client.get("/api/v1/genealogy/export/organizations-csv").text
    assert "Recensement" not in text
    org_json = client.get("/api/v1/genealogy/export/org-json").json()
    assert not any("Recensement" in o["name"] for o in org_json["organizations"])

