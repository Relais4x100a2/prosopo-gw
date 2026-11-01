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


@pytest.mark.parametrize(
    "source",
    [
        "Reg",
        "https://x.example/a?b=c&d=e",
        r"https://x.example/wiki/A\_B\_(1849%E2%80%931928)",
        "3_E_041/472",
    ],
)
def test_source_du_temoin_est_un_seul_mot(source):
    g = GeneWebParser(validate=False).parse_string(
        f"fam A B +1900 C D\nwit m: P Q #occu x #src {source} 22/7/1849 #bp V\n"
        "wit m: R S\nwit m: T U\nbeg\n- h X\nend\n"
    )
    (f,) = g.families.values()
    assert [w["person_id"] for w in f.witnesses] == ["P_Q_0", "R_S_0", "T_U_0"]
    assert g.persons["P_Q_0"].birth_place == "V"
