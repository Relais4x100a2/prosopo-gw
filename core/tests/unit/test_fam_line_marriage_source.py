"""#ms (source du mariage) et #mp sur la ligne fam : le nom de l'épouse survit."""

import pytest

from geneweb_py import GeneWebParser

SOURCES = {
    "url": "https://www.example.org/a4/doc.php?x=Y&k=0&q=Aa%20Bb&z=A%C3%A9#t",
    "slash": "3_E_041/472",
    "html": '_<a_class="visio"_href="Lien',
    "colon": "1802/03/22_-_Cote_4E_-_vue_39/83_-_Filae_:_https://x.example/a",
    "paren": "Reg(Pa",
}


def _famille(ligne: str):
    g = GeneWebParser(validate=False).parse_string(ligne + "\n")
    return list(g.families.values())[0]


@pytest.mark.parametrize("source", SOURCES.values(), ids=SOURCES.keys())
def test_source_de_mariage_n_avale_pas_l_epouse(source):
    f = _famille(
        f"fam DUPONT Jean +11/8/1910 #mp Ville,_80464 #ms {source} MARTIN Anne"
    )
    assert f.husband_id == "DUPONT_Jean_0"
    assert f.wife_id == "MARTIN_Anne_0"


def test_lieu_de_mariage_avec_points_virgules():
    f = _famille("fam DUPONT Jean +11/1/1791 #mp Ville;Autre;Lieu #ms Reg MARTIN Anne")
    assert f.wife_id == "MARTIN_Anne_0"


def test_source_seule_sans_lieu():
    f = _famille("fam DUPONT Jean +2/1894 #ms Registre MARTIN Anne")
    assert f.wife_id == "MARTIN_Anne_0"


@pytest.mark.parametrize(
    "lieu", ["9th_Ave_Presby_Ch", "9e_Arrondissement_-_Paris,_75,_Paris,_FRANCE"]
)
def test_lieu_de_mariage_commencant_par_un_chiffre(lieu):
    g = GeneWebParser(validate=False).parse_string(
        f"fam DUPONT Jean +1900 #mp {lieu} #ms Reg(Pa MARTIN Anne\n"
    )
    (f,) = g.families.values()
    assert f.wife_id == "MARTIN_Anne_0"
    assert f.marriage_place == lieu
