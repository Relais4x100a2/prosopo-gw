"""Sociétés reconnues par leur forme juridique et témoins rattachés à l'organisation.

Fixtures 100 % synthétiques.
"""

import pytest

from geneweb_py.core.event import Event, EventType
from geneweb_py.core.event_to_organization import (
    WITNESS_NOTE,
    WITNESS_ROLE,
    EventToOrganizationMapper,
    _establishment_in,
)
from geneweb_py.core.organization import OrganizationType
from geneweb_py.core.parser.gw_parser import GeneWebParser


def _parse(pevt_body: str):
    text = f"encoding: utf-8\ngwplus\n\npevt DUPONT Jean\n{pevt_body}\nend pevt\n"
    return GeneWebParser().parse_string(text)


def _names(genealogy, links):
    return sorted(genealogy.persons[link.person_id].last_name for link in links)


@pytest.mark.parametrize(
    "text, trigger",
    [
        ("SNC_DUPONT_et_Cie", "snc"),
        ("DUPONT_et_Cie", "cie"),
        ("DUPONT_&_Cie.", "cie"),
        ("SARL_Fictive", "sarl"),
        ("SA_des_Forges_Fictives", "sa"),
        ("SAS_Fictive", "sas"),
        ("Et._DUPONT_Freres", "et."),
        ("Etude_de_Maitre_DUPONT", "etude"),
        ("Étude_DUPONT", "etude"),
        ("Agence_Fictive", "agence"),
        ("Boutique_Fictive", "boutique"),
        ("Comptoir_des_Soies", "comptoir"),
        ("Commandite_DUPONT", "commandite"),
        ("Bureau_Fictif", "bureau"),
        ("Fabrique_de_Rubans", "fabrique"),
        ("Filature_Fictive", "filature"),
    ],
)
def test_company_words_are_recognised(text, trigger):
    assert _establishment_in(text) == (trigger, OrganizationType.COMPANY)


@pytest.mark.parametrize(
    "text",
    [
        "Achat_de_sa_part",
        "Pierre_et_Marie",
        "Et_puis_voyage",
        "Etudes_de_droit",
        "Snc_minuscule",
        "Voyage_sas_aeroport",
    ],
)
def test_ambiguous_forms_are_not_companies(text):
    assert _establishment_in(text) is None


def test_company_tag_with_witnesses_links_every_member():
    g = _parse(
        "#SNC_DUPONT_et_Cie 1922 #p Paris\n"
        "wit m: MARTIN Pierre\n"
        "wit m: LEROY Paul\n"
        "wit f: #godp MOREAU Anne"
    )
    created_orgs, created_links = g.infer_organizations()
    assert (created_orgs, created_links) == (1, 4)
    org = next(iter(g.organizations.values()))
    assert org.type is OrganizationType.COMPANY
    assert org.metadata["trigger"] == "snc"
    links = g.get_organization_links(organization_id=org.id)
    assert _names(g, links) == ["DUPONT", "LEROY", "MARTIN", "MOREAU"]
    holder = [link for link in links if WITNESS_NOTE not in link.notes]
    assert _names(g, holder) == ["DUPONT"]
    roles = {g.persons[link.person_id].last_name: link.role for link in links}
    assert roles["MARTIN"] == WITNESS_ROLE
    assert roles["MOREAU"] == "Parrain ou marraine"
    # même événement d'origine et mêmes dates pour tous
    assert {link.source_event_id for link in links} == {holder[0].source_event_id}
    assert all(link.start_date.sort_year() == 1922 for link in links)


def test_company_tag_without_witnesses_is_an_organization():
    g = _parse("#SNC_DUPONT_et_Cie 1922 #p Paris")
    assert g.infer_organizations() == (1, 1)
    org = next(iter(g.organizations.values()))
    assert org.type is OrganizationType.COMPANY
    assert org.name == "SNC DUPONT et Cie"


@pytest.mark.parametrize(
    "tag, name",
    [
        ("Societe_Fictive_des_Rubans", "Societe Fictive des Rubans"),
        ("société_BASSE_VALLEE", "Société BASSE VALLEE"),
        ("Président_de_la_société_de_pêche", "Société de pêche"),
        (
            'Formation_société_"E._DUPONT_jeune_et_Cie"',
            "Société E. DUPONT jeune et Cie",
        ),
    ],
)
def test_lone_societe_tag_names_the_company(tag, name):
    g = _parse(f"#{tag} 1900 #p Lyon")
    assert g.infer_organizations() == (1, 1)
    org = next(iter(g.organizations.values()))
    assert org.type is OrganizationType.COMPANY
    assert org.name == name


def test_acts_of_one_company_share_the_organization():
    g = _parse(
        '#Formation_société_"E._DUPONT_et_Cie" 1858 #p [Bercy]_-_Paris\n'
        '#Dissolution_société_"E._DUPONT_et_Cie" 1864 #p [Tribunal_de_Commerce]_-_Paris'
    )
    assert g.infer_organizations() == (1, 2)
    org = next(iter(g.organizations.values()))
    assert org.name == "Société E. DUPONT et Cie"
    assert org.type is OrganizationType.COMPANY


@pytest.mark.parametrize(
    "tag",
    [
        "Maison_de_campagne",
        "Achat_maison",
        "Bureau_de_vote",
        "Atelier_peinture",
        "Magasin_Fictif",
        "Boutique_Fictive",
        "Etude_du_piano",
    ],
)
def test_ambiguous_establishment_tag_alone_stays_unclassified(tag):
    g = _parse(f"#{tag} 1900 #p Lyon")
    assert g.infer_organizations() == (0, 0)


@pytest.mark.parametrize(
    "tag, name",
    [
        ("Embauche_usine_Fictive", "Usine Fictive"),
        ("Entreprise_DUPONT_Freres", "Entreprise DUPONT Freres"),
        ("Manufacture_des_Tabacs", "Manufacture des Tabacs"),
        ("Fabrique_de_Rubans", "Fabrique de Rubans"),
        ("Filature_Fictive", "Filature Fictive"),
        ("Banque_Fictive", "Banque Fictive"),
        ("Comptoir_des_Soies", "Comptoir des Soies"),
        ("Agence_Fictive", "Agence Fictive"),
        ("Etablissements_DUPONT", "Etablissements DUPONT"),
        ("Etablissement_DUPONT", "Etablissement DUPONT"),
        ("Compagnie_des_Eaux", "Compagnie des Eaux"),
        ("DUPONT_SA", "DUPONT SA"),
    ],
)
def test_unambiguous_company_words_suffice_alone(tag, name):
    g = _parse(f"#{tag} 1900 #p Lyon")
    if name is None:
        assert g.infer_organizations() == (0, 0)
        return
    assert g.infer_organizations() == (1, 1)
    org = next(iter(g.organizations.values()))
    assert (org.name, org.type) == (name, OrganizationType.COMPANY)


def test_bare_company_word_names_nothing():
    g = _parse("#Visite_usine 1900 #p Lyon")
    assert g.infer_organizations() == (0, 0)


def test_military_compagnie_is_not_a_lone_company():
    g = _parse("#Compagnie_3 1915 #p Verdun")
    assert all(o.type is not OrganizationType.COMPANY for o in g.organizations.values())


def test_witnesses_join_typed_event_organizations():
    g = _parse("#educ 1880 #p [Ecole_Fictive]_-_Lyon\nwit m: DURAND Paul")
    assert g.infer_organizations() == (1, 2)
    links = g.get_organization_links()
    assert _names(g, links) == ["DUPONT", "DURAND"]


def test_witness_is_not_linked_twice_for_the_same_event():
    g = _parse(
        "#SNC_DUPONT_et_Cie 1922 #p Paris\nwit m: MARTIN Pierre\nwit m: MARTIN Pierre"
    )
    assert g.infer_organizations() == (1, 2)


def test_apply_is_idempotent_with_witnesses():
    g = _parse("#SNC_DUPONT_et_Cie 1922 #p Paris\nwit m: MARTIN Pierre")
    assert g.infer_organizations() == (1, 2)
    assert g.infer_organizations() == (0, 0)


def test_plain_tag_with_witnesses_stays_weak():
    event = Event(event_type=EventType.OTHER, event_type_raw="Voyage_Italie")
    mapper = EventToOrganizationMapper()
    proposal = mapper.propose(event, {}, tag_member_counts={"voyage italie": 3})
    assert proposal is None


def test_witness_links_survive_the_sidecar(tmp_path):
    from geneweb_py.formats.org_sidecar import (
        export_organizations,
        import_organizations,
    )

    body = "#SNC_DUPONT_et_Cie 1922 #p Paris\nwit m: MARTIN Pierre"
    g = _parse(body)
    g.infer_organizations()
    path = export_organizations(g, tmp_path / "base.org.json")
    fresh = _parse(body)
    assert import_organizations(fresh, path) == (1, 2)
    witness = [lk for lk in fresh.organization_links if WITNESS_NOTE in lk.notes]
    assert [fresh.persons[lk.person_id].last_name for lk in witness] == ["MARTIN"]
    assert witness[0].role == WITNESS_ROLE


def test_bracketed_complement_with_dash_names_the_organization():
    g = _parse(
        "#educ 1904 #p [Rue_Fictive_-_Petit_seminaire]_-_Lyon\nwit m: DURAND Paul"
    )
    g.infer_organizations()
    org = next(iter(g.organizations.values()))
    assert org.name == "Rue Fictive - Petit seminaire"
    assert org.place == "Lyon"
