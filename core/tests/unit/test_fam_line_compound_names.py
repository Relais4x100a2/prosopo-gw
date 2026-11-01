"""Noms et prénoms composés sur la ligne fam (``/``, ``*``, parenthèses, virgule)."""

import pytest

from geneweb_py import GeneWebParser


def _fam(ligne: str):
    g = GeneWebParser(validate=False).parse_string(ligne + "\n")
    return g, list(g.families.values())[0]


@pytest.mark.parametrize(
    ("nom", "prenom"),
    [
        ("MARTIN*", "Anne"),
        ("MARTIN(Autre)", "Anne"),
        ("_(Dit)_MARTIN", "Anne"),
        ("Aa/_KAHN", "Marie"),
        ("MARTIN", "Anne,_Autre"),
        ("MARTIN", "Anne*"),
    ],
)
@pytest.mark.parametrize("suite", ["", " #apubl", " 1900 #bp Ville"])
def test_epouse_au_nom_compose(nom, prenom, suite):
    g, f = _fam(f"fam DUPONT Jean + {nom} {prenom}{suite}")
    assert f.husband_id == "DUPONT_Jean_0"
    assert f.wife_id == f"{nom}_{prenom}_0"
    assert f.wife_id in g.persons


def test_epoux_au_nom_compose_et_occurrence():
    _, f = _fam("fam MARTIN(Autre) Anne,_Bis.3 + DUPONT Jean.1")
    assert f.husband_id == "MARTIN(Autre)_Anne,_Bis_3"
    assert f.wife_id == "DUPONT_Jean_1"


def test_occurrence_reste_separee_du_prenom():
    _, f = _fam("fam DUPONT Jean.3 + MARTIN Anne.5")
    assert (f.husband_id, f.wife_id) == ("DUPONT_Jean_3", "MARTIN_Anne_5")


def test_alias_entre_guillemets_ne_masque_pas_l_epouse():
    _, f = _fam('fam DUPONT Jean + MARTIN Anne"Dite" #apubl')
    assert f.wife_id == "MARTIN_Anne_0"
