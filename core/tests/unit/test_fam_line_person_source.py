"""Source de personne ``#src`` sur la ligne fam : le nom de l'épouse survit."""

import pytest

from geneweb_py import GeneWebParser


def _famille(ligne: str):
    g = GeneWebParser(validate=False).parse_string(ligne + "\n")
    return list(g.families.values())[0]


@pytest.mark.parametrize(
    "source", ["Reg", "Reg(Pa", "Reg(Pa)", "https://www.example.org/a?x=1&y=2"]
)
def test_source_de_personne_du_mari_avant_le_plus(source):
    f = _famille(
        f"fam DUPONT Jean #src {source} + #noment mf MARTIN Anne #src {source}"
    )
    assert f.husband_id == "DUPONT_Jean_0"
    assert f.wife_id == "MARTIN_Anne_0"


def test_source_de_personne_du_mari_sans_qualificatif():
    f = _famille("fam DUPONT Jean #apubl #src Reg + MARTIN Anne #apubl #src Reg")
    assert f.wife_id == "MARTIN_Anne_0"
