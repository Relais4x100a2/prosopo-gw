"""Statut de la relation sur la ligne fam : ``-`` (divorce), ``#sep``, ``#nm``, ``#eng``."""

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.family import MarriageStatus as S


def _fam(ligne: str):
    g = GeneWebParser(validate=False).parse_string(ligne + "\n")
    return list(g.families.values())[0]


@pytest.mark.parametrize(
    ("ligne", "statut", "divorce"),
    [
        ("fam A B +1900 C D", S.MARRIED, None),
        ("fam A B + - C D", S.DIVORCED, None),
        ("fam A B +1900 - 1950 C D", S.DIVORCED, "1950"),
        ("fam A B + -1987 C D #apriv", S.DIVORCED, "1987"),
        ("fam A B +1900 -<1974 C D", S.DIVORCED, "<1974"),
        ("fam A B +1900 #sep C D", S.SEPARATED, None),
        ("fam A B + #nm C D", S.NOT_MARRIED, None),
        ("fam A B + #eng C D", S.ENGAGED, None),
    ],
)
def test_statut_de_la_relation(ligne, statut, divorce):
    f = _fam(ligne)
    assert f.marriage_status == statut
    assert (str(f.divorce_date) if f.divorce_date else None) == divorce
    assert f.wife_id == "C_D_0"


@pytest.mark.parametrize("ligne", ["fam A B + #nm #sep C D", "fam A B + #sep #nm C D"])
def test_non_marie_et_separe_garde_les_deux_informations(ligne):
    f = _fam(ligne)
    assert f.marriage_status == S.NOT_MARRIED
    assert f.is_separated is True


@pytest.mark.parametrize("ligne", ["fam A B + - ? ?", "fam A B + - 1950 ? ?"])
def test_divorce_avec_conjoint_inconnu_garde_le_statut(ligne):
    f = _fam(ligne)
    assert f.wife_id == "?_?_0"
    assert f.marriage_status == S.DIVORCED
