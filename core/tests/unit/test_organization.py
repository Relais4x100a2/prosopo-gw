"""Modèle Organisation : instanciation, validation, liens personnes, JSON compagnon.

Données 100 % synthétiques.
"""

import json

import pytest

from geneweb_py.core.date import Date
from geneweb_py.core.exceptions import GeneWebValidationError
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.organization import (
    Organization,
    OrganizationLink,
    OrganizationType,
)
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.person import Person
from geneweb_py.formats.org_sidecar import (
    export_organizations,
    import_organizations,
    load_sidecar_for,
    sidecar_path_for,
)


def _person(last="DUPONT", first="Jean"):
    return Person(last_name=last, first_name=first)


def _genealogy():
    genealogy = Genealogy()
    genealogy.add_person(_person())
    genealogy.add_person(_person("MARTIN", "Pierre"))
    return genealogy


class TestOrganizationType:
    def test_members(self):
        assert {t.name for t in OrganizationType} == {
            "COMPANY",
            "SCHOOL",
            "ASSOCIATION",
            "INSTITUTION",
            "RELIGIOUS",
            "MILITARY",
            "OTHER",
        }

    def test_values_are_lowercase_slugs(self):
        assert OrganizationType("school") is OrganizationType.SCHOOL


class TestOrganization:
    def test_defaults(self):
        org = Organization(id="ecole_x", name="Ecole X")
        assert org.type is OrganizationType.OTHER
        assert org.aliases == [] and org.notes == [] and org.sources == []
        assert org.needs_review is False
        assert org.confidence is None and org.parent_id is None

    def test_create_builds_stable_normalised_id(self):
        a = Organization.create("École des Beaux-Arts", place="Lyon")
        b = Organization.create("ecole  des beaux arts", place="LYON")
        assert a.id == b.id == "ecole_des_beaux_arts_lyon"

    def test_create_without_place(self):
        assert Organization.create("Club Sportif").id == "club_sportif"

    def test_place_parts_reuse_place_parser(self):
        org = Organization(id="o", name="Atelier", place="[Atelier Rose] - Lyon")
        assert org.place_parts.complement == "Atelier Rose"
        assert org.place_parts.name == "Lyon"
        assert Organization(id="o", name="X").place_parts is None

    def test_validate_ok(self):
        org = Organization(
            id="o",
            name="Ecole",
            founding_date=Date.parse("1850"),
            dissolution_date=Date.parse("1900"),
            confidence=0.8,
        )
        assert org.validate() == []

    @pytest.mark.parametrize(
        "kwargs, fragment",
        [
            ({"name": "  "}, "nom"),
            ({"confidence": 1.5}, "confidence"),
            ({"confidence": -0.1}, "confidence"),
            ({"parent_id": "o"}, "parent"),
            (
                {
                    "founding_date": Date.parse("1900"),
                    "dissolution_date": Date.parse("1850"),
                },
                "dates",
            ),
        ],
    )
    def test_validate_reports_problems(self, kwargs, fragment):
        params = {"id": "o", "name": "Ecole"}
        params.update(kwargs)
        problems = Organization(**params).validate()
        assert any(fragment in p for p in problems), problems

    def test_dict_roundtrip(self):
        org = Organization(
            id="o",
            name="Ecole",
            type=OrganizationType.SCHOOL,
            aliases=["EBA"],
            founding_date=Date.parse("1850"),
            place="Lyon",
            notes=["n1"],
            sources=["s1"],
            parent_id="u",
            confidence=0.5,
            needs_review=True,
            metadata={"k": 1},
        )
        again = Organization.from_dict(org.to_dict())
        assert again.to_dict() == org.to_dict()
        assert again.type is OrganizationType.SCHOOL
        assert again.founding_date.sort_year() == 1850
        assert again.needs_review is True

    def test_unknown_type_falls_back_to_other_keeping_raw(self):
        org = Organization.from_dict({"id": "o", "name": "X", "type": "guilde"})
        assert org.type is OrganizationType.OTHER
        assert org.type_raw == "guilde"


class TestOrganizationLink:
    def test_fields_and_validation(self):
        link = OrganizationLink(
            person_id="p",
            organization_id="o",
            role="Apprenti",
            start_date=Date.parse("1890"),
            end_date=Date.parse("1895"),
            source_event_id="evt1",
            source_event_type="Cours_peinture",
        )
        assert link.validate() == []
        assert link.role == "Apprenti"

    def test_inverted_period_is_reported(self):
        link = OrganizationLink(
            person_id="p",
            organization_id="o",
            start_date=Date.parse("1900"),
            end_date=Date.parse("1890"),
        )
        assert any("période" in p for p in link.validate())

    def test_dict_roundtrip(self):
        link = OrganizationLink(
            person_id="p",
            organization_id="o",
            role="Membre",
            start_date=Date.parse("~1890"),
            notes=["x"],
        )
        again = OrganizationLink.from_dict(link.to_dict())
        assert again.to_dict() == link.to_dict()


class TestGenealogyIntegration:
    def test_defaults_are_empty_and_independent(self):
        a, b = Genealogy(), Genealogy()
        a.add_organization(Organization(id="o", name="X"))
        assert b.organizations == {} and b.organization_links == []

    def test_add_and_get(self):
        genealogy = _genealogy()
        org = Organization(id="o", name="Ecole")
        genealogy.add_organization(org)
        assert genealogy.get_organization("o") is org
        assert genealogy.get_organization("absent") is None

    def test_duplicate_id_rejected(self):
        genealogy = _genealogy()
        genealogy.add_organization(Organization(id="o", name="Ecole"))
        with pytest.raises(GeneWebValidationError):
            genealogy.add_organization(Organization(id="o", name="Autre"))

    def test_link_and_queries(self):
        genealogy = _genealogy()
        genealogy.add_organization(Organization(id="o", name="Ecole"))
        genealogy.add_organization(Organization(id="c", name="Club"))
        jean, pierre = list(genealogy.persons)
        genealogy.link_person_to_organization(jean, "o", role="Elève")
        genealogy.link_person_to_organization(jean, "o", role="Professeur")
        genealogy.link_person_to_organization(jean, "c")
        genealogy.link_person_to_organization(pierre, "o", role="Elève")

        assert [o.id for o in genealogy.get_person_organizations(jean)] == ["o", "c"]
        assert genealogy.get_person_organizations("inconnu") == []
        assert [p.first_name for p in genealogy.get_organization_members("o")] == [
            "Jean",
            "Pierre",
        ]
        assert len(genealogy.get_organization_links(person_id=jean)) == 3
        assert len(genealogy.get_organization_links(organization_id="o")) == 3

    def test_link_unknown_references_rejected(self):
        genealogy = _genealogy()
        genealogy.add_organization(Organization(id="o", name="Ecole"))
        jean = next(iter(genealogy.persons))
        with pytest.raises(GeneWebValidationError):
            genealogy.link_person_to_organization("inconnu", "o")
        with pytest.raises(GeneWebValidationError):
            genealogy.link_person_to_organization(jean, "absente")

    def test_validate_organizations_detects_cycle_and_missing_parent(self):
        genealogy = _genealogy()
        genealogy.add_organization(Organization(id="a", name="A", parent_id="b"))
        genealogy.add_organization(Organization(id="b", name="B", parent_id="a"))
        genealogy.add_organization(Organization(id="c", name="C", parent_id="zzz"))
        problems = genealogy.validate_organizations()
        assert any("cycle" in p for p in problems)
        assert any("zzz" in p for p in problems)

    def test_validate_organizations_clean(self):
        genealogy = _genealogy()
        genealogy.add_organization(Organization(id="u", name="Université"))
        genealogy.add_organization(Organization(id="f", name="Faculté", parent_id="u"))
        assert genealogy.validate_organizations() == []

    def test_to_dict_unchanged_without_organizations(self):
        assert "organizations" not in Genealogy().to_dict()

    def test_to_dict_exposes_organizations(self):
        genealogy = _genealogy()
        genealogy.add_organization(Organization(id="o", name="Ecole"))
        data = genealogy.to_dict()
        assert data["organizations"][0]["id"] == "o"
        assert data["organization_links"] == []


class TestSidecarJson:
    def _filled(self):
        genealogy = _genealogy()
        genealogy.add_organization(
            Organization(
                id="o",
                name="Ecole",
                type=OrganizationType.SCHOOL,
                founding_date=Date.parse("1850"),
            )
        )
        jean = next(iter(genealogy.persons))
        genealogy.link_person_to_organization(
            jean, "o", role="Elève", start_date=Date.parse("1860")
        )
        return genealogy, jean

    def test_sidecar_path_naming(self):
        assert sidecar_path_for("base/exemple.gw").name == "exemple.org.json"

    def test_export_then_import_roundtrip(self, tmp_path):
        source, jean = self._filled()
        target = tmp_path / "base.org.json"
        export_organizations(source, target)

        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert [o["id"] for o in payload["organizations"]] == ["o"]

        fresh = _genealogy()
        assert import_organizations(fresh, target) == (1, 1)
        assert fresh.get_organization("o").type is OrganizationType.SCHOOL
        link = fresh.get_organization_links(person_id=jean)[0]
        assert link.role == "Elève" and link.start_date.sort_year() == 1860

    def test_missing_sidecar_is_a_noop(self, tmp_path):
        genealogy = _genealogy()
        assert import_organizations(genealogy, tmp_path / "absent.org.json") == (0, 0)
        assert genealogy.organizations == {}

    def test_invalid_json_raises_validation_error(self, tmp_path):
        bad = tmp_path / "bad.org.json"
        bad.write_text("{pas du json", encoding="utf-8")
        with pytest.raises(GeneWebValidationError):
            import_organizations(_genealogy(), bad)

    def test_link_to_unknown_person_raises(self, tmp_path):
        source, _ = self._filled()
        target = tmp_path / "base.org.json"
        export_organizations(source, target)
        with pytest.raises(GeneWebValidationError):
            import_organizations(Genealogy(), target)

    def test_gw_parsing_unaltered_without_sidecar(self, tmp_path):
        gw = tmp_path / "base.gw"
        gw.write_text(
            "encoding: utf-8\ngwplus\n\npevt DUPONT Jean\n"
            "#Cours_peinture 1990\nend pevt\n",
            encoding="utf-8",
        )
        genealogy = GeneWebParser().parse_file(str(gw))
        assert genealogy.organizations == {}
        assert load_sidecar_for(genealogy, gw) == (0, 0)
        assert genealogy.organizations == {}

    def test_load_sidecar_for_picks_companion_file(self, tmp_path):
        gw = tmp_path / "base.gw"
        gw.write_text(
            "encoding: utf-8\ngwplus\n\npevt DUPONT Jean\n#educ 1990\nend pevt\n",
            encoding="utf-8",
        )
        genealogy = GeneWebParser().parse_file(str(gw))
        jean = next(iter(genealogy.persons))
        genealogy.add_organization(Organization(id="o", name="Ecole"))
        genealogy.link_person_to_organization(jean, "o")
        export_organizations(genealogy, sidecar_path_for(gw))

        reparsed = GeneWebParser().parse_file(str(gw))
        assert load_sidecar_for(reparsed, gw) == (1, 1)
