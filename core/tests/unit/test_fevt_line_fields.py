"""Lignes d'événements familiaux ``#marr``/``#div``… : date, lieu et source verbatim."""

from geneweb_py import GeneWebParser

GW = (
    "fam DUPONT Jean +1900 MARTIN Marie\n"
    "fevt\n"
    "#marr 11/5/1932 #p Ville,_80001,_Somme,_France #s 3_E_041/472\n"
    "#div 1/2/1950 #p 5th_Avenue_Church #s Arbre_(https://example.org/x?n=a&p=b&oc=0)\n"
    "#marc 21/4/1920 #p _[rue_du_Renard,_5]_-_Paris,_75004,_France\n"
    "end fevt\n"
)


def _events():
    g = GeneWebParser(validate=False).parse_string(GW)
    return list(g.families.values())[0].events


def test_marr_lieu_et_source_complets():
    e = _events()[0]
    assert e.date is not None and e.date.raw_text == "11/5/1932"
    assert e.place == "Ville,_80001,_Somme,_France"
    assert e.source == "3_E_041/472"


def test_div_lieu_commencant_par_chiffre_et_source_url():
    e = _events()[1]
    assert e.date is not None and e.date.raw_text == "1/2/1950"
    assert e.place == "5th_Avenue_Church"
    assert e.source == "Arbre_(https://example.org/x?n=a&p=b&oc=0)"


def test_tag_libre_inchange():
    e = _events()[2]
    assert e.family_event_type is not None and e.family_event_type.value == "marc"
    assert e.place == "_[rue_du_Renard,_5]_-_Paris,_75004,_France"
