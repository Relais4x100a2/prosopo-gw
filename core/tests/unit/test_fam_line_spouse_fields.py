"""Champs de personne (#bp #dp #bs #ds…) du mari/de l'épouse sur la ligne fam."""

import pytest

from geneweb_py import GeneWebParser


def _famille(ligne: str):
    g = GeneWebParser(validate=False).parse_string(ligne + "\n")
    return list(g.families.values())[0]


def _ok(ligne: str):
    f = _famille(ligne)
    assert f.husband_id == "DUPONT_Jean_0", ligne
    assert f.wife_id == "MARTIN_Anne_0", ligne
    return f


SOURCES = [
    "Reg",
    "Reg(Pa",
    "Reg(9_MIR_9)_p.1_:_https://x.example/a?b=c&d=e",
    "3_E_041/472",
    "1802/03/22_-_Cote_4E",
    '_<a_class="v"_href="L',
]


@pytest.mark.parametrize("src", SOURCES)
@pytest.mark.parametrize("tag", ["bs", "ds", "ps", "rs"])
def test_source_du_mari_est_un_seul_mot(tag, src):
    _ok(
        f"fam DUPONT Jean 1/1/1900 #bp Ville #{tag} {src} 1/1/1950 +1/1/1920 MARTIN Anne"
    )


@pytest.mark.parametrize("src", SOURCES)
def test_source_de_naissance_sans_date_ensuite(src):
    _ok(f"fam DUPONT Jean 1/1/1900 #bs {src} +1/1/1920 #mp Ville MARTIN Anne")


@pytest.mark.parametrize("tag", ["bp", "dp", "pp", "rp"])
def test_lieu_a_crochets_suivi_d_une_date(tag):
    _ok(
        f"fam DUPONT Jean 1/1/1900 #{tag} _[Eglise]_-_Ville,_25,_Doubs 1/1/1950 "
        "+1/1/1920 MARTIN Anne"
    )


def test_lieu_a_crochets_apres_naissance():
    _ok(
        "fam DUPONT Jean 1/1/1900 #bp _[Eglise]_-_Ville,_25,_Doubs +1/1/1920 MARTIN Anne"
    )


def test_deces_inconnu_apres_lieu_de_naissance():
    f = _ok("fam DUPONT Jean 1/1/1900 #bp Ville,_80,_Somme ? +1/1/1920 MARTIN Anne")
    assert f.husband_id == "DUPONT_Jean_0"


def test_deces_inconnu_seul():
    _ok("fam DUPONT Jean 7/6/1992 ? +1/1/2020 MARTIN Anne")


def test_deces_inconnu_de_l_epouse():
    _ok("fam DUPONT Jean +1/1/2020 MARTIN Anne 7/6/1992 #bp Ville ?")


def test_epouse_inconnue_reste_absente():
    assert _famille("fam DUPONT Jean 1/1/1900 ? + ? ?").wife_id is None
