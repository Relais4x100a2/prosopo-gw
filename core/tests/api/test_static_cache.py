"""Le front doit être revalidé : un redéploiement ne laisse pas d'app.js périmé."""

from fastapi.testclient import TestClient

from geneweb_py.api.main import app


def test_static_files_must_be_revalidated():
    with TestClient(app) as client:
        for path in ("/", "/app.js", "/style.css"):
            r = client.get(path)
            assert r.status_code == 200
            assert r.headers["cache-control"] == "no-cache", path
