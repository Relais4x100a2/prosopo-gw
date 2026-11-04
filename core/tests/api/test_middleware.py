"""
Tests pour les middlewares de l'API.
"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from geneweb_py.api.middleware.error_handler import setup_error_handlers
from geneweb_py.api.middleware.logging import setup_logging_middleware


class TestErrorHandler:
    """Tests pour le middleware de gestion d'erreurs."""

    def test_error_handler_setup(self):
        """Test configuration du handler d'erreurs."""
        app = FastAPI()
        setup_error_handlers(app)
        # Le middleware est configuré
        assert app is not None

    def test_http_exception_handling(self):
        """Test gestion des HTTPException."""
        app = FastAPI()
        setup_error_handlers(app)

        @app.get("/test-error")
        async def test_error():
            raise HTTPException(status_code=404, detail="Not found")

        client = TestClient(app)
        response = client.get("/test-error")
        assert response.status_code == 404

    def test_validation_error_handling(self):
        """Test gestion des erreurs de validation."""
        app = FastAPI()
        setup_error_handlers(app)

        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            value: int

        @app.post("/test-validation")
        async def test_validation(item: Item):
            return item

        client = TestClient(app)
        response = client.post(
            "/test-validation", json={"name": "test"}
        )  # Missing value
        assert response.status_code == 422


class TestLoggingMiddleware:
    """Tests pour le middleware de logging."""

    def test_logging_middleware_setup(self):
        """Test configuration du middleware de logging."""
        app = FastAPI()
        setup_logging_middleware(app)
        # Le middleware est configuré
        assert app is not None

    def test_request_logging(self):
        """Test logging des requêtes."""
        app = FastAPI()
        setup_logging_middleware(app)

        @app.get("/test-log")
        async def test_log():
            return {"message": "OK"}

        client = TestClient(app)
        response = client.get("/test-log")
        assert response.status_code == 200
        assert response.json() == {"message": "OK"}

    def test_error_logging(self):
        """Test logging des erreurs dans le middleware."""
        app = FastAPI()
        setup_error_handlers(app)  # D'abord le handler pour capturer les erreurs
        setup_logging_middleware(app)  # Puis le logging

        @app.get("/test-error-log")
        async def test_error():
            raise ValueError("Test error for logging")

        # raise_server_exceptions=False pour ne pas propager l'exception au test
        client = TestClient(app, raise_server_exceptions=False)
        # L'erreur est loggée par le middleware puis gérée par error_handler
        response = client.get("/test-error-log")
        # Le error_handler retourne une réponse 500
        assert response.status_code == 500
        assert "error" in response.json()
        assert response.json()["error"] is True


def test_session_token_not_logged(caplog):
    import logging
    from pathlib import Path

    from fastapi.testclient import TestClient

    from geneweb_py.api.main import create_app

    FIXTURE_GW = Path(__file__).parent.parent / "fixtures" / "simple_test.gw"
    app = create_app()
    secret_token = "SUPERSECRET_SESSION_TOKEN_12345"

    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="geneweb_py"):
        with open(FIXTURE_GW, "rb") as f:
            client.post(
                "/api/v1/sessions",
                files={"file": ("simple_test.gw", f, "application/octet-stream")},
            )
        client.get("/api/v1/persons/", headers={"X-Session-Token": secret_token})

    for record in caplog.records:
        assert secret_token not in record.getMessage(), (
            f"Token found in log record: {record.getMessage()}"
        )


class TestLoggingPrivacy:
    """Aucune donnée du fichier téléversé ne doit atteindre les journaux."""

    SECRET = "DUPONT_Jean_Secret_0"

    @staticmethod
    def _api_logs(caplog) -> str:
        """Journaux de l'API seuls (le client de test httpx écrit sa propre URL)."""
        return "\n".join(
            r.getMessage() + (r.exc_text or "")
            for r in caplog.records
            if r.name.startswith("geneweb_py")
        )

    def _app(self):
        app = FastAPI()
        setup_error_handlers(app)
        setup_logging_middleware(app)

        @app.get("/api/v1/persons/{person_id}")
        async def person(person_id: str):
            return {"id": person_id}

        @app.get("/api/v1/boom/{person_id}")
        async def boom(person_id: str):
            raise ValueError(f"échec pour {person_id}")

        return app

    def test_logs_route_template_not_real_url(self, caplog):
        caplog.set_level("DEBUG")
        client = TestClient(self._app())
        assert (
            client.get(f"/api/v1/persons/{self.SECRET}?query=Secret").status_code == 200
        )
        logs = self._api_logs(caplog)
        assert "DUPONT" not in logs
        assert "Secret" not in logs
        assert "/api/v1/persons/{person_id}" in logs

    def test_unmatched_path_is_not_logged(self, caplog):
        caplog.set_level("DEBUG")
        client = TestClient(self._app())
        assert client.get(f"/inconnu/{self.SECRET}").status_code == 404
        assert "DUPONT" not in self._api_logs(caplog)

    def test_exception_message_and_url_not_logged(self, caplog):
        caplog.set_level("DEBUG")
        client = TestClient(self._app(), raise_server_exceptions=False)
        assert client.get(f"/api/v1/boom/{self.SECRET}").status_code == 500
        logs = self._api_logs(caplog)
        assert "DUPONT" not in logs
        assert "ValueError" in logs

    def test_client_ip_and_user_agent_not_logged(self, caplog):
        caplog.set_level("DEBUG")
        client = TestClient(self._app())
        client.get("/api/v1/persons/x", headers={"User-Agent": "UA-Secret-Marker"})
        logs = self._api_logs(caplog)
        assert "UA-Secret-Marker" not in logs
        assert "testclient" not in logs
