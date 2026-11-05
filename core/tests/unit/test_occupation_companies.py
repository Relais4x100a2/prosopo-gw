"""Entreprise nommée dans la profession de l'état civil, sans « à » ni « chez ».

Fixtures 100 % synthétiques.
"""

import pytest

from geneweb_py.core.event_to_organization import EventToOrganizationMapper
from geneweb_py.core.organization import OrganizationType
from geneweb_py.core.parser.gw_parser import GeneWebParser


def _propose(text: str):
    return EventToOrganizationMapper().propose_from_occupation(text)


@pytest.mark.parametrize(
    "text, name, role",
    [
        ("Employée Banque Fictive de Lyon", "Banque Fictive de Lyon", "Employée"),
        ("comptable Cie du Gaz Fictif", "Cie du Gaz Fictif", "comptable"),
        (
            "Ingénieur, administrateur délégué de la société textile fictive",
            "Société textile fictive",
            "administrateur délégué",
        ),
        ("Directeur d'usine - Fictif Freres", "Fictif Freres", "Directeur"),
        ("chef d'entreprise DUPONT", "Entreprise DUPONT", "chef"),
        ("Contremaître Filature Fictive à Lille", "Filature Fictive", "Contremaître"),
        ("ouvrier, Etablissements DUPONT", "Etablissements DUPONT", "ouvrier"),
        (
            "Directeur à Lyon des Etablissements DUPONT",
            "Etablissements DUPONT",
            "Directeur",
        ),
    ],
)
def test_named_company_in_occupation(text, name, role):
    proposal = _propose(text)
    assert proposal is not None
    assert (proposal.name, proposal.type) == (name, OrganizationType.COMPANY)
    assert proposal.role == role
    assert proposal.named_from == "occupation_text"


@pytest.mark.parametrize(
    "text",
    [
        "Employé de banque",
        "Directeur d'usine",
        "directeur usine",
        "Administrateur de société",
        "Gérante de société",
        "Commis de comptoir",
        "Directeur de filature à Lille",
        "Métreur, chef d'entreprise",
        "Capitaine d'infanterie, compagnie des Grenadiers",
        "ouvrier de fabrique",
        "Directeur de banque et conseiller municipal",
    ],
)
def test_generic_function_names_no_company(text):
    assert _propose(text) is None


def test_place_in_the_role_becomes_the_place():
    proposal = _propose("Directeur à Lyon des Etablissements DUPONT")
    assert proposal is not None and proposal.place == "Lyon"


def test_existing_a_rule_still_wins():
    proposal = _propose("Comptable à la Banque Durand")
    assert proposal is not None and proposal.name == "Banque Durand"


def test_lone_holder_of_a_profession_company_is_a_candidate():
    text = "encoding: utf-8\n\nfam DUPONT Jean #occu Employé_Banque_Fictive + MARTIN Marie\n"
    g = GeneWebParser().parse_string(text)
    assert g.infer_organizations() == (1, 1)
    from geneweb_py.api.services.organization_candidates import build_candidate_index

    index = build_candidate_index(g)
    assert [c.name for c in index.candidates.values()] == ["Banque Fictive"]
