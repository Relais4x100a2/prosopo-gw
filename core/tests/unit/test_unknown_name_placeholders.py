"""Noms et prénoms inconnus écrits ``?``, ``???``, ``_???`` (avec occurrence ``.N``).

Le lexeur les prenait pour des dates : l'époux/se disparaissait de la ligne fam.
Données synthétiques uniquement.
"""

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.parser.lexical import LexicalParser, TokenType


def _parse(texte: str):  # type: ignore[no-untyped-def]
    return GeneWebParser(validate=False).parse_string(texte)


def _ids(texte: str) -> list:  # type: ignore[type-arg]
    return [(f.husband_id, f.wife_id) for f in _parse(texte).families.values()]


@pytest.mark.parametrize(
    ("ligne", "attendu"),
    [
        ("fam ??? Paul + MARTIN Anne", ("???_Paul_0", "MARTIN_Anne_0")),
        ("fam DUPONT ??? + MARTIN Anne", ("DUPONT_???_0", "MARTIN_Anne_0")),
        ("fam ??? ??? + MARTIN Anne", ("???_???_0", "MARTIN_Anne_0")),
        ("fam DUPONT Paul + ??? ???", ("DUPONT_Paul_0", "???_???_0")),
        ("fam DUPONT Paul + ??? Anne", ("DUPONT_Paul_0", "???_Anne_0")),
        ("fam DUPONT Paul + MARTIN ???", ("DUPONT_Paul_0", "MARTIN_???_0")),
        ("fam _??? Paul + MARTIN Anne", ("_???_Paul_0", "MARTIN_Anne_0")),
        ("fam ??? ???.1 + MARTIN Anne", ("???_???_1", "MARTIN_Anne_0")),
        ("fam ? ? + MARTIN Anne", (None, "MARTIN_Anne_0")),
        ("fam ? ?.0 + MARTIN Anne", (None, "MARTIN_Anne_0")),
        ("fam DUPONT Paul + ? ?.0", ("DUPONT_Paul_0", None)),
        (
            "fam DUPONT Paul +1950 #mp Lieu,_France ??? ???",
            ("DUPONT_Paul_0", "???_???_0"),
        ),
    ],
)
def test_inconnus_sur_ligne_fam(ligne: str, attendu: tuple) -> None:  # type: ignore[type-arg]
    assert _ids(ligne + "\n") == [attendu]


def test_les_deux_conjoints_inconnus_restent_distincts() -> None:
    g = _parse("fam ??? ???.1 + ??? ???.2\n")
    (f,) = g.families.values()
    assert (f.husband_id, f.wife_id) == ("???_???_1", "???_???_2")


def test_inconnu_dans_une_ligne_enfant() -> None:
    g = _parse("fam DUPONT Paul + MARTIN Anne\nbeg\n- h ???\n- f ???.1\nend\n")
    (f,) = g.families.values()
    assert sorted(f.child_ids) == ["DUPONT_???_0", "DUPONT_???_1"]


@pytest.mark.parametrize("date", ["?1950", "?25/12/1990", "~1950", "<1950"])
def test_les_dates_incertaines_restent_des_dates(date: str) -> None:
    tokens = LexicalParser(f"fam DUPONT Paul {date} + MARTIN Anne\n").tokenize()
    assert [t.value for t in tokens if t.type == TokenType.DATE] == [date]


def test_inconnus_a_point_d_interrogation_unique_ne_fusionnent_pas() -> None:
    g = _parse("fam ? ?.0 + #noment ? ?.0\nfam ? ?.0 + #noment ? ?.0\n")
    assert [(f.husband_id, f.wife_id) for f in g.families.values()] == [
        (None, None)
    ] * 2
    assert not g.persons


@pytest.mark.parametrize(
    ("ligne", "attendu"),
    [
        ("fam DUPONT Paul + ? Anne", ("DUPONT_Paul_0", "?_Anne_0")),
        ("fam DUPONT Paul +1750 ? Anne 1725 #bp Ville", ("DUPONT_Paul_0", "?_Anne_0")),
        ("fam DUPONT Paul + #nm ? Anne #apriv", ("DUPONT_Paul_0", "?_Anne_0")),
        ("fam DUPONT Paul + MARTIN ?", ("DUPONT_Paul_0", "MARTIN_?_0")),
        ("fam ? Paul + MARTIN Anne", ("?_Paul_0", "MARTIN_Anne_0")),
        ("fam DUPONT Paul + - ? ?", ("DUPONT_Paul_0", None)),
    ],
)
def test_un_seul_point_d_interrogation_reste_une_personne(ligne, attendu):
    assert _ids(ligne + "\n") == [attendu]
