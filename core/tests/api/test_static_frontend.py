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
        for path in ("/vendor/tabulator.min.js", "/vendor/tabulator.min.css"):
            r = client.get(path)
            assert r.status_code == 200
            assert "default-src 'self'" in r.headers["content-security-policy"]


def test_app_js_uses_no_removed_tabulator_editors():
    """Tabulator 6 a retiré l'éditeur « select » (remplacé par « list »)."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"headerFilter:\s*['\"]select['\"]", js)


def test_event_filter_ids_used_by_app_js_exist_in_index():
    """Chaque id lu par app.js dans l'onglet Événements existe dans index.html."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r"getElementById\('(evt-[\w-]+)'\)", js))
    assert ids
    for i in ids:
        assert f'id="{i}"' in html, i


def test_detail_opens_in_side_drawer_not_inside_list():
    """La fiche s'ouvre dans un panneau latéral : la liste reste stable."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for i in ("detail-drawer", "drawer-trail", "drawer-body", "drawer-close"):
        assert f'id="{i}"' in html, i
    # Plus d'insertion de la fiche dans la liste.
    assert "insertAdjacentElement" not in js
    assert "placeDetailPanel" not in js
    # Fil d'Ariane, fermeture au clavier, plein écran sur mobile.
    assert "function pushTrail(" in js and "TRAIL_MAX" in js
    assert "e.key !== 'Escape'" in js
    assert "@media (max-width: 767.98px)" in css
    # Une seule fiche à la fois : un seul compteur d'annulation.
    assert "_personDetailSeq" not in js and "_familyDetailSeq" not in js
    assert js.count('class="text-muted list-empty"') == 2


def test_every_event_type_code_has_a_french_label():
    """Aucun code brut (« resi »…) ne doit s'afficher dans l'onglet Événements."""
    from geneweb_py.core.event import EventType, FamilyEventType

    js = (STATIC / "app.js").read_text(encoding="utf-8")
    labelled = set(re.findall(r"\{ value: '(\w+)',\s*label:", js))
    codes = {t.value for t in EventType} | {t.value for t in FamilyEventType}
    assert codes - labelled == set()


def test_tabulator_uses_light_theme_overridden_by_app_css():
    """Thème Tabulator clair, surchargé par style.css (chargé après)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "midnight" not in html
    tab = html.index("/vendor/tabulator.min.css")
    assert tab < html.index("/style.css")
    assert ".tabulator-row.tabulator-row-even" in (STATIC / "style.css").read_text(
        encoding="utf-8"
    )


def test_visible_names_go_through_formatter():
    """Les champs de nom bruts (« Jean_Pierre ») ne sont jamais affichés tels quels."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function formatGwName(" in js
    assert not re.search(r"escHtml\(\w+\.(surname|first_name)\)", js)
    assert not re.search(r"\(\w+\.surname \|\| '—'\) \+ ', '", js)


def test_drop_starts_upload_immediately():
    """Déposer ou choisir un fichier lance le chargement sans clic supplémentaire."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "startUpload(e.dataTransfer.files[0])" in js
    assert "if (file) startUpload(file);" in js


def test_names_resolved_in_batch_not_one_request_per_person():
    """Anti N+1 : les noms passent par GET /persons/names, avec un cache."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    body = js[js.index("async function resolvePersonNames(") :]
    body = body[: body.index("\n}\n")]
    assert "/api/v1/persons/names?" in body
    assert "'/api/v1/persons/' + encodeURIComponent" not in body
    assert "state.nameCache" in body


def test_events_fetch_is_capped():
    """La recherche d'événements ne peut pas enchaîner un nombre illimité de pages."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "page >= EVT_MAX_PAGES" in js


def test_views_are_driven_by_hash_routes():
    """Onglets et fiches passent par l'adresse (#/…) : retour, rechargement, liens."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "window.addEventListener('hashchange', applyRoute)" in js
    for route in ("personnes", "personne", "familles", "famille", "evenements"):
        assert f"{route}:" in js or f"'{route}'" in js
    # Plus d'ouverture directe de fiche depuis un clic : tout passe par navigate().
    assert "showPersonDetail" not in js and "showFamilyDetail" not in js
    assert 'href="${escHtml(personHash(' in js
