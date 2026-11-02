"""Fidélité textuelle : lieux entre crochets et notes à l'identique (synthétique)."""

from geneweb_py import GeneWebParser


def _parse(texte: str):
    return GeneWebParser(validate=False).parse_string(texte)


def test_lieu_entre_crochets_sur_la_ligne_fam():
    g = _parse("fam DUPONT Paul +1750 #mp [Eglise]_-_Chartres MARTIN Anne\n")
    (fam,) = g.families.values()
    assert fam.marriage_place == "[Eglise] - Chartres"
    assert fam.wife_id == "MARTIN_Anne_0"


def test_lieu_entre_crochets_naissance_et_deces():
    g = _parse(
        "fam DUPONT Paul 1720 #bp [Moulin]_-_Dreux 1790 #dp [Hospice]_-_Chartres +1750 MARTIN Anne\n"
    )
    p = g.persons["DUPONT_Paul_0"]
    assert p.birth_place == "[Moulin] - Dreux"
    assert p.death_place == "[Hospice] - Chartres"


def test_note_de_personne_garde_ponctuation_et_crochets():
    g = _parse(
        "notes DUPONT Paul\nbeg\nLaboureur aisé, voir [[DUPONT Luc]].\nend notes\n"
    )
    assert g.persons["DUPONT_Paul_0"].notes == ["Laboureur aisé, voir [[DUPONT Luc]]."]


def test_note_de_personne_multi_lignes_garde_les_retours():
    g = _parse("notes DUPONT Paul\nbeg\nLigne un.\nLigne deux (suite).\nend notes\n")
    assert g.persons["DUPONT_Paul_0"].notes == ["Ligne un.\nLigne deux (suite)."]


def test_note_d_evenement_pevt_garde_la_ponctuation():
    g = _parse(
        "pevt DUPONT Paul\n#bapt 3/3/1751\nnote Acte lisible, f°42v.\nend pevt\n"
    )
    assert g.persons["DUPONT_Paul_0"].events[0].notes == ["Acte lisible, f°42v."]


def test_comm_de_famille_garde_la_ponctuation():
    g = _parse(
        "fam DUPONT Paul +1750 MARTIN Anne\ncomm Mariage contesté, voir (acte).\n"
    )
    (fam,) = g.families.values()
    assert fam.comments == ["Mariage contesté, voir (acte)."]
