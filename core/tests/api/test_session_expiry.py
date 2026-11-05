"""Expiration visible côté client : temps restant renvoyé, prolongation explicite."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.session_store import SessionStore

FIXTURE_GW = Path(__file__).parent.parent / "fixtures" / "simple_test.gw"


@pytest.fixture
def client():
    from geneweb_py.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _create_session(client) -> dict:
    with open(FIXTURE_GW, "rb") as f:
        resp = client.post(
            "/api/v1/sessions",
            files={"file": ("simple_test.gw", f, "application/octet-stream")},
        )
    assert resp.status_code == 201
    return resp.json()


def test_create_returns_remaining_seconds(client):
    data = _create_session(client)
    assert 0 < data["expires_in"] <= 3600


def test_every_session_request_reports_remaining_time(client):
    token = _create_session(client)["session_token"]
    resp = client.get("/api/v1/persons/", headers={"X-Session-Token": token})
    assert resp.status_code == 200
    assert 3590 <= int(resp.headers["X-Session-Expires-In"]) <= 3600


def test_refresh_extends_and_reports(client):
    token = _create_session(client)["session_token"]
    resp = client.post("/api/v1/sessions/refresh", headers={"X-Session-Token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert 3590 <= body["expires_in"] <= 3600
    assert "expires_at" in body
    assert resp.headers["Cache-Control"] == "no-store"


def test_refresh_unknown_session_is_401(client):
    resp = client.post("/api/v1/sessions/refresh", headers={"X-Session-Token": "nope"})
    assert resp.status_code == 401


def test_store_touch_returns_expiry_and_slides():
    store = SessionStore(ttl_seconds=60)
    token, first = store.create(object())  # type: ignore[arg-type]
    touched = store.touch(token)
    assert touched is not None
    genealogy, expires_at = touched
    assert expires_at >= first
    assert store.touch("inconnu") is None
