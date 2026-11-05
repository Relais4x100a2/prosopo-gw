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
    assert js.count('class="text-muted list-empty"') == 3


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
    for route in (
        "personnes",
        "personne",
        "familles",
        "famille",
        "evenements",
        "organisations",
        "organisation",
    ):
        assert f"{route}:" in js or f"'{route}'" in js
    # Plus d'ouverture directe de fiche depuis un clic : tout passe par navigate().
    assert "showPersonDetail" not in js and "showFamilyDetail" not in js
    assert 'href="${escHtml(personHash(' in js


def test_stats_charts_link_to_filtered_views():
    """Stats visuelles : chaque barre mène à la liste ou aux événements filtrés."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for fn in ("function decadeChart(", "function barCard(", "function coverageCard("):
        assert fn in js, fn
    # Filtres posés par les graphiques, lus depuis l'adresse puis passés à l'API.
    assert "personsListHash(1, '', { nom: r.surname })" in js
    assert "params.set('birth_year_from', years[0])" in js
    assert "'#/evenements?type=' + encodeURIComponent(code)" in js
    assert "applyEventsRoute(route.params)" in js
    assert 'id="persons-filters"' in html
    # Aucune bibliothèque de graphiques : HTML/CSS seulement (CSP self).
    assert "chart.js" not in html.lower() and "<canvas" not in js


def test_tabs_are_keyboard_accessible_buttons():
    """Motif ARIA « tabs » : vrais boutons, ←/→/Début/Fin, tabindex itinérant."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'role="tablist"' in html
    assert html.count('role="tab"') == 6 and html.count('role="tabpanel"') == 6
    assert not re.search(r'<div class="pgw-tab[ "]', html)
    assert len(re.findall(r'<button type="button" class="pgw-tab', html)) == 6
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in js
    assert "t.setAttribute('aria-selected', String(on))" in js
    assert "t.tabIndex = on ? 0 : -1" in js


def test_search_runs_while_typing_in_persons_and_families():
    """Recherche à la frappe (pause, minimum de caractères), aussi dans Familles."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function wireInstantSearch(" in js
    assert js.count("wireInstantSearch(searchInput,") == 2
    assert "SEARCH_DEBOUNCE_MS" in js and "SEARCH_MIN_CHARS" in js
    # Une frappe ne crée pas une entrée d'historique par lettre.
    assert "location.replace(hash)" in js
    for i in ("families-search", "families-search-btn", "families-clear-btn"):
        assert f'id="{i}"' in html, i
    assert "params.set('query', query)" in js


def test_session_expiry_banner_extend_and_expired_screen():
    """Compte à rebours recalé sur le serveur, bandeau « Prolonger », écran d'expiration."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for i in ("session-banner", "session-extend", "view-expired", "expired-reload"):
        assert f'id="{i}"' in html, i
    assert "Prolonger" in html and "Recharger le fichier" in html
    assert "const SESSION_EXPIRES_IN_HEADER = 'X-Session-Expires-In'" in js
    assert "res.headers.get(SESSION_EXPIRES_IN_HEADER)" in js
    assert "'/api/v1/sessions/refresh'" in js
    assert "SESSION_WARN_MS = 5 * 60 * 1000" in js
    # À zéro, la bascule se fait sans attendre une erreur 401.
    assert "if (remaining <= 0) { handleExpiry(); return; }" in js


def test_person_detail_has_timeline_notes_and_sources():
    """Fiche personne : frise des événements, notes/sources repliables, lien Événements."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "related_to: personId, degree: '1'" in js
    assert "function buildTimelineSection(" in js
    assert '<ol class="timeline">' in js
    assert js.count('<details class="drawer-details">') == 2
    assert "Voir dans Événements" in js
    # Le lien pose la personne dans les filtres de l'onglet Événements.
    assert "params.get('personne')" in js and "setEvtPerson(personne)" in js


def test_source_link_points_to_monorepo():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "https://github.com/Relais4x100a2/prosopo-gw" in html
    assert "github.com/Relais4x100a2/geneweb-py" not in html


def test_events_table_shows_custom_type_column():
    """« Autre » : le nom personnalisé (tag libre) a sa propre colonne."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "field: 'custom_type'" in js and "title: 'Nom personnalisé'" in js
    assert "visible: data.some(d => d.custom_type)" in js
    # Deux « Autre » distincts dans les stats : personnel et familial.
    assert "{ value: 'other', label: 'Autre (famille)' }" in js


def test_organizations_tab_routes_list_and_detail():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="tab-organizations"' in html and 'id="panel-organizations"' in html
    assert (
        html.index('id="tab-events"')
        < html.index('id="tab-organizations"')
        < html.index('id="tab-stats"')
    )
    for i in (
        "orgs-sort",
        "orgs-type",
        "orgs-source",
        "orgs-search",
        "orgs-list",
        "orgs-unmatched",
        "orgs-unmatched-body",
    ):
        assert f'id="{i}"' in html, i
    assert "organisations: 'organizations'" in js
    assert "organisation: 'organizations'" in js
    assert "name === 'organisation'" in js
    assert "function openOrganizationDetail(" in js
    assert "function renderUnmatched(" in js
    assert "'/api/v1/organizations/candidates" in js
    assert "'/api/v1/organizations/unmatched'" in js
    assert "drawerError('Impossible de charger l" in js
    assert "Pourquoi cette proposition" in js
    assert js.count('class="text-muted list-empty"') == 3


def test_organizations_visible_values_are_labelled():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    from geneweb_py.core.organization import OrganizationType

    for t in OrganizationType:
        assert f"{t.value}:" in js, t
    for source in ("tag", "place", "typed_event", "occupation_text"):
        assert f"{source}:" in js
    assert "formatGwName(org.name)" in js or "formatGwName(o.name)" in js


def test_export_tab_offers_organization_files():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for i in (
        "btn-export-org-json",
        "btn-export-org-csv",
        "btn-export-org-links-csv",
    ):
        assert f'id="{i}"' in html, i
    assert "#valider-et-enrichir" in html
    assert "'organization-links-csv': 'liens_organisations.csv'" in js
    assert "EXPORT_EXT" not in js


def test_stats_show_candidate_count_linking_to_tab():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "'/api/v1/organizations/candidates?size=1'" in js
    assert "Organisations candidates" in js and "#/organisations" in js
