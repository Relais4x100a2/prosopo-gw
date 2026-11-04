"""
Le front statique est servi avec une CSP ``default-src 'self'`` : toute
ressource externe (CDN) y est bloquée par le navigateur. Ces tests évitent
qu'une dépendance (ex. Tabulator) soit de nouveau chargée depuis un CDN.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from geneweb_py.api.main import app

STATIC = Path(__file__).resolve().parents[2] / "src/geneweb_py/api/static"


def _local_refs(html: str) -> list:
    return re.findall(r'(?:src|href)="(/[^"]+)"', html)


def test_index_has_no_external_resources():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    # Ressources chargées uniquement (les liens <a href> de navigation sont libres).
    external = re.findall(
        r'<(?:script|link|img)\b[^>]*?(?:src|href)="(https?://[^"]+)"', html
    )
    assert external == []


def test_every_local_asset_referenced_by_index_exists():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = _local_refs(html)
    assert "/vendor/tabulator.min.js" in refs
    for ref in refs:
        assert (STATIC / ref.lstrip("/")).is_file(), ref


def test_tabulator_assets_are_served_with_self_only_csp():
    with TestClient(app) as client:
        for path in ("/vendor/tabulator.min.js", "/vendor/tabulator_midnight.min.css"):
            r = client.get(path)
            assert r.status_code == 200
            assert "default-src 'self'" in r.headers["content-security-policy"]


def test_app_js_uses_no_removed_tabulator_editors():
    """Tabulator 6 a retiré l'éditeur « select » (remplacé par « list »)."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"headerFilter:\s*['\"]select['\"]", js)
