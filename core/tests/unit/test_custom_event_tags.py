"""Tags d'événements libres : un tag est un mot sans espace (accents, guillemets, apostrophes)."""

import pytest

from geneweb_py import GeneWebParser

TAGS = [
    "Amitié",
    "Période_occupation",
    "Achat_d'un_bien",
    'Vente_des_"Ets_Un"_"Ets_Deux"',
    "Amitié_-_entraide",
    "Séparation_de_biens",
]


@pytest.mark.parametrize("tag", TAGS)
def test_fevt_tag_libre_non_ascii_garde(tag):
    g = GeneWebParser(validate=False).parse_string(
        f"fam DUPONT Jean +1900 MARTIN Anne\nfevt\n#marr 1900\n#{tag} 1910 #p Lieu\n"
        "#resi 1920\nend fevt\nbeg\n- h Paul\nend\n"
    )
    (f,) = g.families.values()
    assert len(f.events) == 3
    assert f.events[1].event_type_raw == tag
    assert f.events[1].place == "Lieu"


@pytest.mark.parametrize("tag", TAGS)
def test_pevt_tag_libre_non_ascii_garde(tag):
    g = GeneWebParser(validate=False).parse_string(
        f"pevt DUPONT Jean\n#birt 1880\n#{tag} 1910 #p Lieu\n#deat 1950\nend pevt\n"
    )
    evs = g.persons["DUPONT_Jean_0"].events
    assert [e.event_type_raw for e in evs if e.event_type_raw] == [tag]
    assert len(evs) == 3


def _pevt(header, extra=""):
    return GeneWebParser(validate=False).parse_string(
        f"fam DUPONT Jean +1900 MARTIN Anne\nbeg\n- h Paul\nend\n{extra}"
        f"pevt {header}\n#birt 1880\n#deat 1950\nend pevt\n"
    )


def test_pevt_numero_occurrence_rattache_a_la_bonne_personne():
    g = _pevt("DUPONT Jean.1", "fam DUPONT Jean.1 +1901 MARTIN Zoe\n")
    assert len(g.persons["DUPONT_Jean_1"].events) == 2
    assert len(g.persons["DUPONT_Jean_0"].events) == 0


@pytest.mark.parametrize(
    ("header", "pid"),
    [
        ("DE/_B Anne", "DE/_B_Anne_0"),
        ('MARTIN Anne_"Dit"', 'MARTIN_Anne_"Dit"_0'),
        ('MARTIN Anne_"Dit".2', 'MARTIN_Anne_"Dit"_2'),
        ("MARTIN Anne_(Jr)", "MARTIN_Anne_(Jr)_0"),
        ("MARTIN Marie,_Anne.3", "MARTIN_Marie,_Anne_3"),
        ("MARTIN Anne_W.", "MARTIN_Anne_W._0"),
    ],
)
def test_pevt_entete_nom_compose(header, pid):
    g = _pevt(header)
    assert len(g.persons[pid].events) == 2
