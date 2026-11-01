"""Code de sexe (mf/mm/ff/?…) après #noment, #residence… sur la ligne fam."""

import pytest

from geneweb_py import GeneWebParser


def _famille(ligne: str):
    g = GeneWebParser(validate=False).parse_string(ligne + "\n")
    return list(g.families.values())[0]


@pytest.mark.parametrize(
    "tag", ["noment", "nsck", "nsckm", "banns", "contract", "license"]
)
@pytest.mark.parametrize("code", ["mf", "mm", "ff", "m?", "?f"])
def test_code_de_sexe_apres_qualificatif_connu(tag, code):
    f = _famille(f"fam DUPONT Jean 0 + #{tag} {code} MARTIN Anne")
    assert f.husband_id == "DUPONT_Jean_0"
    assert f.wife_id == "MARTIN_Anne_0"


@pytest.mark.parametrize("tag", ["residence", "pacs"])
def test_code_de_sexe_apres_evenement_de_relation(tag):
    f = _famille(
        f"fam DUPONT Jean +1858 #{tag} mf #mp _[rue_X]_-_Ville,_Alger MARTIN Anne"
    )
    assert f.wife_id == "MARTIN_Anne_0"


def test_qualificatif_sans_code():
    f = _famille("fam DUPONT Jean 0 + #noment MARTIN Anne #apubl")
    assert f.wife_id == "MARTIN_Anne_0"


def test_epouse_inconnue_apres_qualificatif_reste_absente():
    f = _famille("fam DUPONT Jean 0 + #noment mf ? ?")
    assert f.wife_id is None


def test_conjoint_dont_le_nom_ressemble_a_un_code_sans_qualificatif():
    f = _famille("fam DUPONT Jean + MF Anne")
    assert f.wife_id == "MF_Anne_0"
