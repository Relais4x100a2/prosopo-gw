"""
Tests du filtrage côté serveur de la recherche d'événements
(personne liée + degré, nom de famille, types multiples).

Base synthétique uniquement (noms fictifs).
"""

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW_SOURCE = """\
fam DUPONT Jean +1900 #mp Lyon MARTIN Marie
beg
- h Paul 1925
end

fam BERNARD Luc +1950 #mp Paris LEROY Anne
beg
- f Zoe 1960
end

fam DUPONT Paul +1950 #mp Nantes ROUX Éloïse
"""


@pytest.fixture
def service() -> GenealogyService:
    genealogy = GeneWebParser().parse_string(GW_SOURCE)
    return GenealogyService(genealogy)


def _pid(service: GenealogyService, first: str, last: str) -> str:
    for p in service.genealogy.persons.values():
        if p.first_name == first and p.last_name == last:
            return p.unique_id
    raise AssertionError(f"{first} {last} introuvable")


def _hit_ids(service: GenealogyService, params: dict) -> set:
    hits, _ = service.search_events({"page": 1, "size": 1000, **params})
    return {(h.person_id, h.family_id, h.event.event_type) for h in hits}


def _persons_of(hits_params: dict, service: GenealogyService) -> set:
    hits, _ = service.search_events({"page": 1, "size": 1000, **hits_params})
    return {h.person_id for h in hits if h.person_id}


class TestRelatedFilter:
    def test_degree_1_keeps_self_and_spouse_only(self, service):
        jean = _pid(service, "Jean", "DUPONT")
        marie = _pid(service, "Marie", "MARTIN")
        paul = _pid(service, "Paul", "DUPONT")
        persons = _persons_of({"related_to": jean, "degree": 1}, service)
        assert paul not in persons
        assert persons <= {jean, marie}

    def test_degree_2_includes_children(self, service):
        jean = _pid(service, "Jean", "DUPONT")
        paul = _pid(service, "Paul", "DUPONT")
        zoe = _pid(service, "Zoe", "BERNARD")
        persons = _persons_of({"related_to": jean, "degree": 2}, service)
        assert paul in persons
        assert zoe not in persons

    def test_related_includes_events_of_their_families(self, service):
        jean = _pid(service, "Jean", "DUPONT")
        hits, _ = service.search_events(
            {"page": 1, "size": 1000, "related_to": jean, "degree": 1}
        )
        assert any(h.family_id is not None for h in hits)
        assert all(
            h.family_id is None
            or service.genealogy.families[h.family_id].husband_id == jean
            for h in hits
        )

    def test_total_counts_filtered_hits_not_all(self, service):
        jean = _pid(service, "Jean", "DUPONT")
        _, total_all = service.search_events({"page": 1, "size": 1000})
        _, total_rel = service.search_events(
            {"page": 1, "size": 1, "related_to": jean, "degree": 2}
        )
        assert 0 < total_rel < total_all

    def test_unknown_person_yields_nothing(self, service):
        hits, total = service.search_events(
            {"page": 1, "size": 10, "related_to": "inconnu_0", "degree": 2}
        )
        assert hits == [] and total == 0

    def test_combined_with_place(self, service):
        jean = _pid(service, "Jean", "DUPONT")
        hits, _ = service.search_events(
            {"page": 1, "size": 100, "related_to": jean, "degree": 2, "place": "lyon"}
        )
        assert hits and all("Lyon" in (h.event.place or "") for h in hits)


class TestFamilyNameFilter:
    def test_matches_person_name_accent_and_case_insensitive(self, service):
        persons = _persons_of({"family_name": "dupont"}, service)
        assert persons == {_pid(service, "Paul", "DUPONT")}
        hits, _ = service.search_events(
            {"page": 1, "size": 100, "family_name": "DUPONT"}
        )
        assert {h.family_id for h in hits if h.family_id} == {"FAM_001", "FAM_003"}

    def test_matches_family_label(self, service):
        hits, _ = service.search_events(
            {"page": 1, "size": 100, "family_name": "leroy"}
        )
        assert hits and all(h.family_id is not None for h in hits)

    def test_accents_ignored(self, service):
        hits, _ = service.search_events(
            {"page": 1, "size": 100, "family_name": "eloise"}
        )
        assert hits


class TestEventTypeFilter:
    def test_string_type_matches_enum_valued_events(self, service):
        births = _hit_ids(service, {"event_type": "birt"})
        assert births and all(
            evt == "birt" or str(evt.value) == "birt" for *_, evt in births
        )

    def test_enum_input_still_accepted(self, service):
        from geneweb_py.core.models import EventType

        assert _hit_ids(service, {"event_type": EventType.BIRTH}) == _hit_ids(
            service, {"event_type": "birt"}
        )


class TestMultipleTypes:
    def test_event_types_union_without_duplicates(self, service):
        births = _hit_ids(service, {"event_type": "birt"})
        marriages = _hit_ids(service, {"event_type": "marr"})
        both = _hit_ids(service, {"event_types": ["birt", "marr"]})
        assert births and marriages
        assert both == births | marriages


class TestRouterPassThrough:
    def test_query_params_reach_service(self):
        captured = {}

        class FakeService:
            genealogy = None

            def search_events(self, params):
                captured.update(params)
                return [], 0

        app.dependency_overrides[get_session_service] = lambda: FakeService()
        try:
            r = TestClient(app).get(
                "/api/v1/events/",
                params={
                    "related_to": "p1",
                    "degree": 3,
                    "family_name": "Dupont",
                    "event_type": "birt,marr",
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200
        assert captured["related_to"] == "p1"
        assert captured["degree"] == 3
        assert captured["family_name"] == "Dupont"
        assert captured["event_types"] == ["birt", "marr"]
        assert "event_type" not in captured

    def test_invalid_degree_rejected(self):
        app.dependency_overrides[get_session_service] = lambda: object()
        try:
            r = TestClient(app).get("/api/v1/events/", params={"degree": 9})
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 422
