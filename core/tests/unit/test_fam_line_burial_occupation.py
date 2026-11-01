"""Inhumation (#buri/#crem/#rp/#rs) et profession (#occu) avant le '+' de la ligne fam."""

import pytest

from geneweb_py import GeneWebParser


def _ok(ligne: str):
    g = GeneWebParser(validate=False).parse_string(ligne + "\n")
    f = list(g.families.values())[0]
    assert f.husband_id == "DUPONT_Jean_0", ligne
    assert f.wife_id == "MARTIN_Anne_0", ligne
    return g


@pytest.mark.parametrize("tag", ["buri", "crem"])
def test_inhumation_avec_date_et_lieu(tag):
    _ok(
        f"fam DUPONT Jean 1/1/1900 #dp Ville #{tag} 5/1/1950 #rp Lieu,_25,_Doubs + MARTIN Anne"
    )


@pytest.mark.parametrize("tag", ["buri", "crem"])
def test_inhumation_sans_date(tag):
    _ok(
        f"fam DUPONT Jean 1/1/1900 #dp Ville #{tag} #rp _[cimetière_X]_-_Ville,_Oise + MARTIN Anne"
    )


def test_inhumation_avec_source():
    _ok("fam DUPONT Jean 1/1/1900 #buri 5/1/1950 #rp Lieu #rs Reg + MARTIN Anne")


@pytest.mark.parametrize(
    "occu",
    [
        "Cultivateur",
        "importer,_Butcher",
        "Maire(1850),_percepteur_à_Toul",
        "professeur_de_théologie_à_Lausanne",
    ],
)
def test_profession_est_un_seul_mot(occu):
    _ok(f"fam DUPONT Jean #occu {occu} 1/1/1900 #bp Ville +1/1/1920 MARTIN Anne")


def test_source_de_naissance_avec_apostrophe_et_point():
    _ok("fam DUPONT Jean 1/1/1900 #bs 9._L'Acte 1/1/1950 +1/1/1920 MARTIN Anne")


def test_date_d_inhumation_va_a_la_personne():
    g = _ok("fam DUPONT Jean 1/1/1900 #buri 5/1/1950 #rp Lieu + MARTIN Anne")
    p = g.persons["DUPONT_Jean_0"]
    assert p.burial_place == "Lieu"
