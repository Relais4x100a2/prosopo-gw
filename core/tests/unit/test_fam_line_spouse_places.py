"""Un lieu #bp / #dp à virgules sur la ligne fam ne doit pas devenir l'épouse.

Le lexeur découpe ``Ville,_Code,_Pays`` en jetons séparés par des virgules ;
les restes du lieu étaient lus comme nom/prénom de l'épouse. Données synthétiques.
"""

import pytest

from geneweb_py import GeneWebParser


def _parse(texte: str):  # type: ignore[no-untyped-def]
    return GeneWebParser(validate=False).parse_string(texte)


@pytest.mark.parametrize(
    "lieu",
    [
        "Ville,_Ville,_Pays",
        "Ville,_Ville,_Cote_d’Ivoire",
        "Ville,_Ville,_Cote_d'Ivoire",
    ],
)
def test_lieu_naissance_a_virgules_du_mari_ne_cree_pas_d_epouse(lieu: str) -> None:
    g = _parse(
        f"fam DUPONT Jean #occu Cadre 30/4/1973 #bp {lieu} "
        "+8/2002 #mp Lieu,_France MARTIN Marie\n"
    )
    (famille,) = g.families.values()
    assert famille.husband_id == "DUPONT_Jean_0"
    assert famille.wife_id == "MARTIN_Marie_0"
    assert g.persons["DUPONT_Jean_0"].birth_place == lieu


def test_lieu_deces_a_virgules_de_l_epouse_est_complet() -> None:
    g = _parse(
        "fam DUPONT Jean + MARTIN Marie 1/1/1950 #dp Ville,_Ville,_Pays #occu Cadre\n"
    )
    (famille,) = g.families.values()
    assert famille.wife_id == "MARTIN_Marie_0"
    assert g.persons["MARTIN_Marie_0"].death_place == "Ville,_Ville,_Pays"
