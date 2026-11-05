"""Index des candidates : état civil écarté, organisations faibles retirées."""

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
#Mariage 1900 #p [Mairie]_-_Lille
#Reconnaissance_enfant 1901
#Recensement 1906 #p Lille
#Philatelie_Locale 1900
#Passage_Fictif_7 1910
#Contrat_Engagement 1912
#educ 1880 #p [Ecole_Saint_Paul]_-_Lille
end pevt

pevt MARTIN Marie
#Mariage 1900 #p [Mairie]_-_Lille
#Reconnaissance_enfant 1902
#Recensement 1906 #p Lille
#Philatelie_Locale 1905
#Passage_Fictif_7 1911
#Contrat_Engagement 1913
#educ 1882 #p [Ecole_Saint_Paul]_-_Lille
end pevt

pevt DURAND Paul
#Recensement 1906 #p Lille
end pevt
"""


def _genealogy():
    return GeneWebParser().parse_string(GW)


def _names(index):
    return {c.name.replace("_", " ") for c in index.candidates.values()}


def _unmatched_tags(index):
    return {e.event_type_raw for g in index.unmatched_groups for e in g.events}


def _refs_of(genealogy, tag_prefix):
    return {
        (pid, i)
        for pid, p in genealogy.persons.items()
        for i, e in enumerate(p.events)
        if (e.event_type_raw or "").startswith(tag_prefix)
    }


def test_civil_status_never_candidate_nor_unmatched():
    index = build_candidate_index(_genealogy())
    for name in _names(index):
        assert not any(w in name for w in ("Mairie", "Mariage", "Recensement"))
    tags = _unmatched_tags(index)
    assert not any(
        t.startswith(("Mariage", "Reconnaissance", "Recensement")) for t in tags
    )
    assert (
        index.civil_status_total == 7
    )  # 2 mariages, 2 reconnaissances, 3 recensements


def test_contrat_engagement_is_not_civil_status():
    index = build_candidate_index(_genealogy())
    assert "Contrat_Engagement" in _unmatched_tags(index)


def test_weak_tag_organization_is_dropped():
    g = _genealogy()
    index = build_candidate_index(g)
    assert "Philatelie Locale" not in _names(index)
    assert not (_refs_of(g, "Philatelie") & index.matched)


def test_address_and_typed_candidates_kept():
    g = _genealogy()
    index = build_candidate_index(g)
    by_name = {c.name.replace("_", " "): c for c in index.candidates.values()}
    assert by_name["Passage Fictif 7"].named_from == "address"
    school = next(c for n, c in by_name.items() if "Saint Paul" in n)
    assert school.named_from in ("typed_event", "place")
    assert _refs_of(g, "Passage_Fictif") <= index.matched
    assert any(
        ref in index.matched
        for ref in {
            (pid, i)
            for pid, p in g.persons.items()
            for i, e in enumerate(p.events)
            if e.event_type.value == "educ"
        }
    )


def test_default_ignored_words_empty():
    assert DEFAULT_IGNORED_WORDS == ()


def test_civil_and_ignored_counted_once():
    index = build_candidate_index(_genealogy(), ["recensement", "domicile"])
    assert index.ignored_total == 0
    assert index.civil_status_total == 7


def test_unmatched_endpoint_has_civil_status_total():
    service = GenealogyService(_genealogy())
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        body = TestClient(app).get("/api/v1/organizations/unmatched").json()
    finally:
        app.dependency_overrides.clear()
    assert body["civil_status_total"] == 7
    assert body["ignored_total"] == 0


def test_sidecar_weak_tag_organization_is_filtered():
    from geneweb_py.core.organization import (
        Organization,
        OrganizationLink,
        OrganizationType,
    )

    g = _genealogy()
    g.infer_organizations()
    org = Organization(
        id="org_weak", name="Faible", type=OrganizationType.OTHER, confidence=0.5
    )
    org.metadata["named_from"] = "tag"
    g.organizations["org_weak"] = org
    for pid in list(g.persons)[:2]:
        g.organization_links.append(
            OrganizationLink(person_id=pid, organization_id="org_weak")
        )
    index = build_candidate_index(g)
    assert "org_weak" not in index.candidates


@pytest.mark.parametrize("name", ["civil_status_total", "matched"])
def test_index_fields_default_safely(name):
    from geneweb_py.api.services.organization_candidates import CandidateIndex

    idx = CandidateIndex({}, 0, [])
    assert getattr(idx, name) in (0, frozenset())
