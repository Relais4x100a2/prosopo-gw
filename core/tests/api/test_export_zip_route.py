"""Routes de l'archive d'export et de son résumé (fixtures 100 % synthétiques)."""

import csv
import io
import json
import zipfile
from datetime import date, datetime
from typing import Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.parser.gw_parser import GeneWebParser

ZIP = "/api/v1/genealogy/export/zip"
SUMMARY = "/api/v1/genealogy/export/summary"

GW = """encoding: utf-8

fam DUPONT Jean + MARTIN Marie
beg
end

pevt DUPONT Jean
#occu 1900 #p [Banque Fictive] - Lyon
end pevt

pevt MARTIN Marie
#occu 1902 #p [Banque Fictive] - Lyon
end pevt

pevt DURAND Paul
#Voyage_Italie 1950 #p Montfictif
end pevt

notes DURAND Paul
beg
Apprenti dans une usine du quartier.
end notes
"""

GW_BARE = """encoding: utf-8

fam DUPONT Jean + MARTIN Marie
beg
end
"""


@pytest.fixture
def client() -> Iterator[TestClient]:
    from geneweb_py.api.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _session(client: TestClient, gw: str = GW, filename: str = "base-test.gw") -> str:
    resp = client.post(
        "/api/v1/sessions",
        files={"file": (filename, gw.encode("utf-8"), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["session_token"])


def _h(token: str) -> Dict[str, str]:
    return {"X-Session-Token": token}


def _archive(client: TestClient, token: str) -> zipfile.ZipFile:
    resp = client.get(ZIP, headers=_h(token))
    assert resp.status_code == 200
    return zipfile.ZipFile(io.BytesIO(resp.content))


def _csv_rows(archive: zipfile.ZipFile, table: str) -> List[Dict[str, str]]:
    (name,) = [n for n in archive.namelist() if n.endswith(f"/{table}.csv")]
    text = archive.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def test_zip_route_returns_named_archive(client: TestClient) -> None:
    token = _session(client)
    resp = client.get(ZIP, headers=_h(token))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["cache-control"] == "no-store"
    today = date.today().isoformat()
    assert resp.headers["content-disposition"] == (
        f'attachment; filename="prosopo-base-test-{today}.zip"'
    )
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert len(names) == 16
    assert any(n.endswith("pistes.csv") for n in names)


def test_source_name_kept_out_of_metadata(client: TestClient) -> None:
    token = _session(client)
    entry = client.app.state.session_store._store[token]  # type: ignore[attr-defined]
    assert entry.genealogy.metadata.source_file is None
    assert entry.source_name == "base-test.gw"


def test_zip_name_from_unsafe_upload_name(client: TestClient) -> None:
    token = _session(client, filename="../ma base (x)!.gw")
    header = client.get(ZIP, headers=_h(token)).headers["content-disposition"]
    today = date.today().isoformat()
    assert header == f'attachment; filename="prosopo-ma_base__x__-{today}.zip"'
    assert header.count('"') == 2 and "/" not in header


def test_service_without_source_name_falls_back_to_base() -> None:
    g = GeneWebParser(validate=False).parse_string(GW_BARE)
    now = datetime(2026, 1, 2, 3, 4, 5)
    name, data = GenealogyService(g).export_bundle(now)
    assert name == "prosopo-base-2026-01-02.zip"
    assert zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_zip_uses_session_ignored_words(client: TestClient) -> None:
    token = _session(client)
    before = _csv_rows(_archive(client, token), "pistes")
    assert any("usine" in r["mots"].split() for r in before)
    put = client.put(
        "/api/v1/organizations/ignored-words",
        json={"words": ["usine"]},
        headers=_h(token),
    )
    assert put.status_code == 200
    archive = _archive(client, token)
    companion = json.loads(archive.read("base.org.json"))
    assert "usine" in companion["ignored_words"]
    assert all("usine" not in r["mots"].split() for r in _csv_rows(archive, "pistes"))
    assert client.get(SUMMARY, headers=_h(token)).json()["pistes"] == 0


def test_export_routes_require_session(client: TestClient) -> None:
    for path in (ZIP, SUMMARY):
        # En-tête absent : 422, comme toutes les routes de session.
        assert client.get(path).status_code == 422
        assert client.get(path, headers=_h("inconnu")).status_code == 401


def test_summary_counts(client: TestClient) -> None:
    token = _session(client)
    resp = client.get(SUMMARY, headers=_h(token))
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert resp.json() == {
        "personnes": 3,
        "organisations": 1,
        "a_classer": 1,
        "pistes": 1,
    }


def test_summary_matches_zip_tables(client: TestClient) -> None:
    token = _session(client)
    summary = client.get(SUMMARY, headers=_h(token)).json()
    archive = _archive(client, token)
    assert len(_csv_rows(archive, "personnes")) == summary["personnes"]
    assert len(_csv_rows(archive, "organisations")) == summary["organisations"]
    assert len(_csv_rows(archive, "reste_a_classer")) == summary["a_classer"]
    assert len(_csv_rows(archive, "pistes")) == summary["pistes"]


def test_zip_for_base_without_organizations(client: TestClient) -> None:
    token = _session(client, gw=GW_BARE, filename="vide.gw")
    assert len(_archive(client, token).namelist()) == 16
    assert client.get(SUMMARY, headers=_h(token)).json() == {
        "personnes": 2,
        "organisations": 0,
        "a_classer": 0,
        "pistes": 0,
    }


def test_existing_export_routes_still_served(client: TestClient) -> None:
    token = _session(client)
    for fmt in (
        "gedcom",
        "json",
        "xml",
        "org-json",
        "organizations-csv",
        "organization-links-csv",
        "shared-experiences-csv",
    ):
        resp = client.get(f"/api/v1/genealogy/export/{fmt}", headers=_h(token))
        assert resp.status_code == 200, fmt
