"""Test d'intégration du flux complet de session éphémère."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE_GW = Path(__file__).parent.parent / "fixtures" / "simple_test.gw"


@pytest.fixture
def client():
    from geneweb_py.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _create_session(client) -> str:
    with open(FIXTURE_GW, "rb") as f:
        resp = client.post(
            "/api/v1/sessions",
            files={"file": ("simple_test.gw", f, "application/octet-stream")},
        )
    assert resp.status_code == 201
    return resp.json()["session_token"]


class TestFullSessionFlow:
    def test_upload_query_delete(self, client):
        token = _create_session(client)

        resp = client.get("/api/v1/persons/", headers={"X-Session-Token": token})
        assert resp.status_code == 200

        resp = client.delete(f"/api/v1/sessions/{token}")
        assert resp.status_code == 204

        resp = client.get("/api/v1/persons/", headers={"X-Session-Token": token})
        assert resp.status_code == 401

    def test_missing_token_returns_422(self, client):
        resp = client.get("/api/v1/persons/")
        assert resp.status_code == 422

    def test_expired_token_returns_401(self, client):
        token = _create_session(client)
        store = client.app.state.session_store
        store._store[token].expires_at = datetime.now(UTC) - timedelta(seconds=1)
        resp = client.get("/api/v1/persons/", headers={"X-Session-Token": token})
        assert resp.status_code == 401

    def test_session_cap_returns_503(self, client):
        store = client.app.state.session_store
        original_max = store._max
        store._max = 1
        try:
            _create_session(client)
            with open(FIXTURE_GW, "rb") as f:
                resp = client.post(
                    "/api/v1/sessions",
                    files={"file": ("simple_test.gw", f, "application/octet-stream")},
                )
            assert resp.status_code == 503
        finally:
            store._max = original_max

    def test_two_sessions_are_isolated(self, client):
        store = client.app.state.session_store
        store._max = 10
        token1 = _create_session(client)
        token2 = _create_session(client)

        resp1 = client.get("/api/v1/persons/", headers={"X-Session-Token": token1})
        resp2 = client.get("/api/v1/persons/", headers={"X-Session-Token": token2})
        assert resp1.status_code == 200
        assert resp2.status_code == 200

        client.delete(f"/api/v1/sessions/{token1}")
        resp1_after = client.get(
            "/api/v1/persons/", headers={"X-Session-Token": token1}
        )
        resp2_after = client.get(
            "/api/v1/persons/", headers={"X-Session-Token": token2}
        )
        assert resp1_after.status_code == 401
        assert resp2_after.status_code == 200

    def test_source_file_not_stored(self, client):
        token = _create_session(client)
        store = client.app.state.session_store
        genealogy = store._store[token].genealogy
        assert genealogy.metadata.source_file is None

    def test_data_endpoints_have_cache_control_no_store(self, client):
        token = _create_session(client)
        resp = client.get("/api/v1/persons/", headers={"X-Session-Token": token})
        assert resp.headers.get("cache-control") == "no-store"


class TestReadOnlyMode:
    def test_write_blocked_in_read_only_mode(self, client, monkeypatch):
        import geneweb_py.api.limits as limits_module

        monkeypatch.setattr(limits_module, "READ_ONLY", True)

        token = _create_session(client)
        resp = client.post(
            "/api/v1/persons/",
            json={"first_name": "Jean", "surname": "Dupont", "sex": "M"},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 405

    def test_reads_allowed_in_read_only_mode(self, client, monkeypatch):
        import geneweb_py.api.limits as limits_module

        monkeypatch.setattr(limits_module, "READ_ONLY", True)

        token = _create_session(client)
        resp = client.get("/api/v1/persons/", headers={"X-Session-Token": token})
        assert resp.status_code == 200
