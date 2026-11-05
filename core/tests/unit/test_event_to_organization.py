"""Déduction d'organisations depuis les événements personnalisés (#strng).

Fixtures 100 % synthétiques.
"""

from geneweb_py.core.event_to_organization import (
    EventContext,
    EventToOrganizationMapper,
    OrganizationProposal,
    event_ref,
    parse_event_ref,
)
from geneweb_py.core.organization import OrganizationType
from geneweb_py.core.parser.gw_parser import GeneWebParser


def _parse(pevt_body: str):
    text = f"encoding: utf-8\ngwplus\n\npevt DUPONT Jean\n{pevt_body}\nend pevt\n"
    parser = GeneWebParser()
    return parser.parse_string(text)


def _parse_two(body_a: str, body_b: str):
    """Deux personnes synthétiques, un bloc pevt chacune."""
    text = (
        "encoding: utf-8\ngwplus\n\n"
        f"pevt DUPONT Jean\n{body_a}\nend pevt\n\n"
        f"pevt MARTIN Marie\n{body_b}\nend pevt\n"
    )
    return GeneWebParser().parse_string(text)


def _parse_attr(occupation: str):
    """Profession en attribut (hors événement) du premier conjoint."""
    text = f"encoding: utf-8\n\nfam DUPONT Jean #occu {occupation} + MARTIN Marie\n"
    return GeneWebParser().parse_string(text)


def _parse_two_attrs(a: str, b: str):
    text = f"encoding: utf-8\n\nfam DUPONT Jean #occu {a} + MARTIN Marie #occu {b}\n"
    return GeneWebParser().parse_string(text)


def _jean(genealogy):
    return next(p for p in genealogy.persons.values() if p.last_name == "DUPONT")


class TestDeterministicRules:
    def test_place_complement_becomes_organization(self):
        g = _parse("#Cours_peinture 1890 #p [Atelier_Rose]_-_Lyon")
        assert g.infer_organizations() == (1, 1)
        org = g.get_organization("atelier_rose_lyon")
        assert org.name == "Atelier Rose"
        assert org.place == "Lyon"
        link = g.get_organization_links(person_id=next(iter(g.persons)))[0]
        assert link.source_event_type == "Cours_peinture"
        assert link.start_date.sort_year() == 1890
        assert link.role == "Élève"
        assert link.source_event_id == "pevt:DUPONT_Jean_0:0"
        assert org.type is OrganizationType.COMPANY and org.confidence == 0.8
        assert org.metadata["named_from"] == "place"
        assert org.metadata["trigger"] == "atelier"
        assert org.metadata["tag"] == "peinture"
        assert org.aliases == []

    def test_tag_wins_over_complement_without_establishment_word(self):
        g = _parse("#Membre_Academie 1900 #p [Salle_Rameau]_-_Lyon")
        g.infer_organizations()
        org = g.get_organization("academie_lyon")
        assert org.name == "Academie" and org.metadata["named_from"] == "tag"
        assert org.metadata["complement"] == "Salle Rameau" and org.aliases == []
        assert org.type is OrganizationType.SCHOOL  # mot d'établissement « académie »

    def test_role_only_tag_with_plain_complement_is_to_determine(self):
        g = _parse("#Membre 1890 #p [Les_Amis_du_Vieux_Lyon]_-_Lyon")
        g.infer_organizations()
        org = g.get_organization("les_amis_du_vieux_lyon_lyon")
        assert org.name == "Les Amis du Vieux Lyon"
        assert org.metadata["to_determine"] is True
        assert org.needs_review is True and org.confidence == 0.5
        assert org.type is OrganizationType.ASSOCIATION  # règle « membre »

    def test_name_taken_from_tag_remainder(self):
        g = _parse("#Membre_Academie 1900")
        assert g.infer_organizations() == (1, 1)
        org = g.get_organization("academie")
        assert org.name == "Academie"
        assert org.type is OrganizationType.SCHOOL  # mot d'établissement « académie »
        link = g.get_organization_links()[0]
        assert link.role == "Membre"

    def test_camel_case_tag_is_split_and_typed(self):
        g = _parse("#Eleve_BeauxArts 1885 #p Paris")
        g.infer_organizations()
        org = next(iter(g.organizations.values()))
        assert org.name == "Beaux Arts"
        assert org.type is OrganizationType.SCHOOL
        assert org.place == "Paris"
        assert g.get_organization_links()[0].role == "Élève"

    def test_tag_without_signal_is_ignored(self):
        g = _parse("#Action-Sociale 1905\n#Membre_1900")
        assert g.infer_organizations() == (0, 0)

    def test_standard_events_are_ignored(self):
        g = _parse("#resi 1890 #p [Lycee_Hugo]_-_Lyon")
        assert g.infer_organizations() == (0, 0)

    def test_same_organization_is_shared_between_events(self):
        g = _parse("#Membre_Academie 1900\n#Membre_Academie 1910")
        assert g.infer_organizations() == (1, 2)

    def test_inference_is_idempotent(self):
        g = _parse("#Membre_Academie 1900")
        assert g.infer_organizations() == (1, 1)
        assert g.infer_organizations() == (0, 0)
        assert len(g.organization_links) == 1

    def test_deterministic_result_is_flagged_by_confidence(self):
        g = _parse(
            "#Membre 1900 #p [Les_Amis_X]_-_Lyon\n"
            "#Cours_peinture 1890 #p [Atelier_Rose]_-_Lyon"
        )
        g.infer_organizations()
        assert g.get_organization("les_amis_x_lyon").needs_review is True
        assert g.get_organization("atelier_rose_lyon").needs_review is False
        assert 0 < g.get_organization("les_amis_x_lyon").confidence < 1


class _Recorder:
    """Hook LLM factice : enregistre les contextes et renvoie une réponse fixe."""

    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.contexts = []

    def __call__(self, context: EventContext):
        self.contexts.append(context)
        if self.error:
            raise self.error
        return self.answer


class TestLLMHook:
    def test_not_called_when_rules_are_confident(self):
        hook = _Recorder()
        g = _parse("#Cours_peinture 1890 #p [Atelier_Rose]_-_Lyon")
        g.infer_organizations(EventToOrganizationMapper(llm=hook))
        assert hook.contexts == []

    def test_called_for_ambiguous_event_and_enriches(self):
        hook = _Recorder(
            OrganizationProposal(
                name="Société Archéologique",
                type=OrganizationType.ASSOCIATION,
                role="Secrétaire",
                confidence=0.9,
            )
        )
        g = _parse("#Action-Sociale 1905\nnote Secrétaire de la Société Archéologique")
        assert g.infer_organizations(EventToOrganizationMapper(llm=hook)) == (1, 1)

        context = hook.contexts[0]
        assert context.event_type_raw == "Action-Sociale"
        assert context.notes == ["Secrétaire de la Société Archéologique"]
        assert context.heuristic is None

        org = next(iter(g.organizations.values()))
        assert org.name == "Société Archéologique"
        assert org.confidence == 0.9 and org.needs_review is False
        assert g.get_organization_links()[0].role == "Secrétaire"

    def test_hook_refines_low_confidence_heuristic(self):
        hook = _Recorder(
            OrganizationProposal(
                name="Académie de Lyon",
                type=OrganizationType.INSTITUTION,
                confidence=0.85,
            )
        )
        g = _parse("#Membre 1900 #p [Les_Amis_X]_-_Lyon")
        g.infer_organizations(EventToOrganizationMapper(llm=hook))
        assert hook.contexts[0].heuristic.name == "Les Amis X"
        org = next(iter(g.organizations.values()))
        assert org.name == "Académie de Lyon"
        assert "Les Amis X" in org.aliases
        assert g.get_organization_links()[0].role == "Membre"

    def test_hook_returning_none_keeps_heuristic_for_review(self):
        g = _parse("#Membre 1900 #p [Les_Amis_X]_-_Lyon")
        g.infer_organizations(EventToOrganizationMapper(llm=_Recorder(None)))
        assert g.get_organization("les_amis_x_lyon").needs_review is True

    def test_hook_error_does_not_break_inference(self):
        hook = _Recorder(error=RuntimeError("API indisponible"))
        g = _parse(
            "#Membre 1900 #p [Les_Amis_X]_-_Lyon\n#Action-Sociale 1905\nnote Un texte"
        )
        assert g.infer_organizations(EventToOrganizationMapper(llm=hook)) == (1, 1)
        assert g.get_organization("les_amis_x_lyon").needs_review is True


class TestInjectableRules:
    def test_default_rules_are_exposed_and_untouched_by_custom_rules(self):
        from geneweb_py.core.event_to_organization import (
            DEFAULT_PREFIX_RULES,
            PrefixRule,
        )

        before = dict(DEFAULT_PREFIX_RULES)
        EventToOrganizationMapper(
            custom_rules={
                "Compagnon": PrefixRule("Compagnon", OrganizationType.COMPANY)
            }
        )
        assert DEFAULT_PREFIX_RULES == before
        assert "membre" in DEFAULT_PREFIX_RULES

    def test_custom_prefix_extends_the_rules(self):
        from geneweb_py.core.event_to_organization import PrefixRule

        g = _parse("#Compagnon_Forge 1850")
        assert g.infer_organizations() == (0, 0)
        mapper = EventToOrganizationMapper(
            custom_rules={
                "compagnon": PrefixRule("Compagnon", OrganizationType.COMPANY)
            }
        )
        assert g.infer_organizations(mapper) == (1, 1)
        assert g.get_organization("forge").type is OrganizationType.COMPANY
        assert g.get_organization_links()[0].role == "Compagnon"

    def test_custom_rule_overrides_a_default_one(self):
        from geneweb_py.core.event_to_organization import PrefixRule

        g = _parse("#Membre_Forge 1900")
        mapper = EventToOrganizationMapper(
            custom_rules={
                "Membre": PrefixRule("Sociétaire", OrganizationType.INSTITUTION)
            }
        )
        g.infer_organizations(mapper)
        assert g.get_organization_links()[0].role == "Sociétaire"
        assert g.get_organization("forge").type is OrganizationType.INSTITUTION


class TestOtherEventRules:
    def test_establishment_word_in_complement_sets_type_and_trigger(self):
        g = _parse("#Reunion 1900 #p [Usine_Martin]_-_Roubaix")
        g.infer_organizations()
        org = g.get_organization("usine_martin_roubaix")
        assert org.type is OrganizationType.COMPANY and org.confidence == 0.8
        assert org.metadata["named_from"] == "place"
        assert org.metadata["trigger"] == "usine"
        assert org.metadata["tag"] == "Reunion"
        assert org.metadata["to_determine"] is False

    def test_tag_without_prefix_needs_two_persons(self):
        one = _parse("#Cercle_Philatelique 1900")
        assert one.infer_organizations() == (0, 0)
        two = _parse_two("#Cercle_Philatelique 1900", "#Cercle_Philatelique 1905")
        assert two.infer_organizations() == (1, 2)
        org = two.get_organization("cercle_philatelique")
        assert org.confidence == 0.5 and org.needs_review is True
        assert org.type is OrganizationType.ASSOCIATION
        assert org.metadata["trigger"] == "cercle"

    def test_relation_word_marks_a_circle(self):
        g = _parse_two("#Amitie_Peintres 1900", "#Amitie_Peintres 1901")
        g.infer_organizations()
        org = g.get_organization("amitie_peintres")
        assert org.type is OrganizationType.OTHER and org.needs_review is True
        assert "relation" in org.notes and org.metadata["trigger"] == "amitie"

    def test_compagnie_followed_by_number_is_military(self):
        g = _parse("#Membre 1914 #p [Compagnie_3]_-_Lille")
        g.infer_organizations()
        assert g.get_organization("compagnie_3_lille").type is OrganizationType.MILITARY

    def test_unshared_tag_with_plain_complement_is_to_determine(self):
        g = _parse("#Cercle_Philatelique 1900 #p [Salle_Rameau]_-_Lyon")
        g.infer_organizations()
        org = g.get_organization("salle_rameau_lyon")
        assert org.metadata["to_determine"] is True
        assert org.metadata["tag"] == "Cercle Philatelique"
        assert org.confidence == 0.5 and org.aliases == []


class TestEventRef:
    def test_roundtrip_and_invalid(self):
        assert event_ref("DUPONT_Jean_0", 3) == "pevt:DUPONT_Jean_0:3"
        assert parse_event_ref("pevt:DUPONT_Jean_0:3") == ("DUPONT_Jean_0", 3)
        assert parse_event_ref(None) is None
        assert parse_event_ref("autre:x:1") is None
        assert parse_event_ref("pevt:x:y") is None


class TestTypedEvents:
    def test_occupation_event_with_complement_creates_company(self):
        g = _parse("#occu 1895 #p [Usine_Martin]_-_Roubaix\nnote Contremaître")
        assert g.infer_organizations() == (1, 1)
        org = g.get_organization("usine_martin_roubaix")
        link = g.get_organization_links(organization_id=org.id)[0]
        assert org.type is OrganizationType.COMPANY and org.confidence == 0.8
        assert org.metadata["named_from"] == "typed_event"
        assert link.role == "Contremaître" and link.source_event_type == "occu"
        assert link.start_date.sort_year() == 1895

    def test_establishment_word_overrides_default_type(self):
        g = _parse("#occu 1895 #p [Lycée_Pasteur]_-_Lille")
        g.infer_organizations()
        assert g.get_organization("lycee_pasteur_lille").type is OrganizationType.SCHOOL

    def test_each_typed_event_gets_its_role(self):
        cases = {
            "educ": "élève",
            "grad": "diplômé",
            "degr": "diplômé",
            "adhe": "membre",
            "hosp": "patient",
            "mser": "soldat",
            "demm": "soldat",
            "elec": "élu",
            "ordn": "ordonné",
        }
        for code, role in cases.items():
            g = _parse(f"#{code} 1900 #p [Maison_X]_-_Lyon")
            g.infer_organizations()
            assert g.organization_links[0].role == role, code

    def test_residence_and_census_never_match(self):
        g = _parse("#resi 1900 #p [Maison_X]_-_Lyon\n#cens 1901 #p [Usine_Y]_-_Lyon")
        assert g.infer_organizations() == (0, 0)

    def test_typed_event_without_complement_gives_nothing(self):
        assert _parse("#educ 1900 #p Lyon").infer_organizations() == (0, 0)


class TestOccupationText:
    def test_attribute_with_establishment_word(self):
        g = _parse_attr("Comptable_à_la_Banque_Durand")
        assert g.infer_organizations() == (1, 1)
        org = g.get_organization("banque_durand")
        link = g.organization_links[0]
        assert org.type is OrganizationType.COMPANY and org.confidence == 0.7
        assert org.metadata["named_from"] == "occupation_text"
        assert org.metadata["trigger"] == "banque"
        assert link.role == "Comptable" and link.source_event_type == "occu_attr"
        assert link.source_event_id is None and link.start_date is None

    def test_chez_without_establishment_word_needs_review(self):
        g = _parse_attr("Ouvrier_chez_Durand")
        g.infer_organizations()
        org = g.get_organization("durand")
        assert org.confidence == 0.5 and org.needs_review is True

    def test_plain_or_village_occupation_gives_nothing(self):
        for text in (
            "Instituteur",
            "Cultivateur_à_Saint-Pierre",
            "Employé_de_commerce",
        ):
            assert _parse_attr(text).infer_organizations() == (0, 0), text

    def test_only_first_comma_part_is_read(self):
        g = _parse_attr("Instituteur,_puis_directeur_de_l'École_Normale")
        assert g.infer_organizations() == (0, 0)

    def test_occupation_event_note_without_complement_uses_city(self):
        g = _parse("#occu 1895 #p Roubaix\nnote Tisseur à l'Usine Martin")
        g.infer_organizations()
        org = g.get_organization("usine_martin_roubaix")
        assert org.place == "Roubaix"
        assert g.organization_links[0].source_event_type == "occu"

    def test_shared_plain_occupation_is_never_an_organization(self):
        g = _parse_two_attrs("Instituteur", "Instituteur")
        assert g.infer_organizations() == (0, 0)


class TestMerge:
    def test_typed_event_and_other_event_merge_on_same_organization(self):
        g = _parse_two(
            "#occu 1895 #p [Usine_Martin]_-_Roubaix",
            "#Reunion 1900 #p [Usine_Martin]_-_Roubaix",
        )
        assert g.infer_organizations() == (1, 2)
        org = g.get_organization("usine_martin_roubaix")
        assert org.metadata["named_from"] == "typed_event"
        types = sorted(link.source_event_type for link in g.organization_links)
        assert types == ["Reunion", "occu"]

    def test_merge_keeps_best_confidence_and_clears_review(self):
        g = _parse_two(
            "#Salle_Rameau 1895 #p [Bureau_Y]_-_Lyon",
            "#occu 1900 #p [Bureau_Y]_-_Lyon",
        )
        g.infer_organizations()
        # « bureau » n'est pas un mot d'établissement : 0,5 à déterminer + 0,8 typé
        org = g.get_organization("bureau_y_lyon")
        assert org.confidence == 0.8 and org.needs_review is False
        assert org.metadata["to_determine"] is False

    def test_two_events_of_one_person_give_two_links(self):
        g = _parse("#Membre_Academie 1900\n#Membre_Academie 1910")
        assert g.infer_organizations() == (1, 2)
        assert [link.source_event_id for link in g.organization_links] == [
            "pevt:DUPONT_Jean_0:0",
            "pevt:DUPONT_Jean_0:1",
        ]
