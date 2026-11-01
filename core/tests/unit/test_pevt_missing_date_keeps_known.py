"""``#birt``/``#deat`` sans date dans ``pevt`` n'efface pas une date déjà connue."""

from geneweb_py import GeneWebParser


def _personne(gw):
    return GeneWebParser(validate=False).parse_string(gw).persons["DUPONT_Jean_0"]


def test_date_connue_conservee():
    p = _personne(
        "fam DUPONT Jean 1/1/1900 #bp Ville_A 2/2/1970 #dp Ville_B + MARTIN Marie\n\n"
        "pevt DUPONT Jean\n#birt #p Ville_A\n#deat #p Ville_B\nend pevt\n"
    )
    assert p.birth_date is not None and p.birth_date.year == 1900
    assert p.death_date is not None and p.death_date.year == 1970


def test_sans_date_connue_reste_inconnue():
    p = _personne(
        "fam DUPONT Jean + MARTIN Marie\n\npevt DUPONT Jean\n#birt\n#deat\nend pevt\n"
    )
    assert p.birth_date is not None and p.birth_date.is_unknown
    assert p.death_date is not None and p.death_date.is_unknown
