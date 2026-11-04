"""
Tests pour l'application principale FastAPI.
"""

from fastapi.testclient import TestClient

from geneweb_py.api.main import app


class TestMainApp:
    """Tests pour l'application FastAPI principale."""

    def test_app_creation(self):
        """Test que l'application est créée correctement."""
        assert app is not None
        assert app.title == "GeneWeb-py API"
        assert app.version == "0.1.0"

    def test_root_endpoint(self):
        """Test endpoint racine — sert désormais l'interface HTML."""
        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert b"prosopo-gw-webapp" in response.content

    def test_security_headers_on_root(self):
        """Les en-têtes de sécurité de base sont présents sur les réponses."""
        client = TestClient(app)
        response = client.get("/")

        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Referrer-Policy") == "no-referrer"
        assert "Content-Security-Policy" in response.headers

    def test_health_endpoint(self):
        """Test endpoint de santé."""
        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["message"] == "GeneWeb-py API is running"
        assert data["version"] == "0.1.0"

    def test_openapi_endpoint(self):
        """Test que l'OpenAPI est disponible."""
        client = TestClient(app)
        response = client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "info" in data

    def test_docs_endpoint(self):
        """Test que la documentation Swagger est disponible."""
        client = TestClient(app)
        response = client.get("/docs")

        assert response.status_code == 200

    def test_redoc_endpoint(self):
        """Test que ReDoc est disponible."""
        client = TestClient(app)
        response = client.get("/redoc")

        assert response.status_code == 200

    def test_static_csp_for_non_api_paths(self):
        """Les chemins non-API doivent recevoir le CSP front-end (default-src 'self')."""
        client = TestClient(app)
        response = client.get("/")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
