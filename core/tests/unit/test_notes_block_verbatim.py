"""Bloc ``notes`` : le texte est conservé tel quel et rattaché à la bonne personne."""

import pytest

from geneweb_py import GeneWebParser

DEFS = "fam DUPONT Jean +1900 MARTIN Anne\nbeg\n- h Paul\nend\n"


def _notes(header, corps, defs=DEFS):
    g = GeneWebParser(validate=False).parse_string(
        f"{defs}notes {header}\nbeg\n{corps}\nend notes\n"
    )
    return g


def test_texte_identique_lignes_guillemets_espaces():
    corps = (
        'Il dit "oui".\n\nDeux  espaces et\xa0nbsp.\n  ligne indentée\n<br>\n- tiret'
    )
    g = _notes("DUPONT Jean", corps)
    assert g.persons["DUPONT_Jean_0"].notes == [corps]


def test_pre_et_balises_conserves():
    corps = '<pre>\n-- ligne a\nfam X Y\n</pre>\n<p style="text-align:left">x</p>'
    g = _notes("DUPONT Jean", corps)
    assert g.persons["DUPONT_Jean_0"].notes == [corps]
    assert "X_Y_0" not in g.persons


def test_numero_occurrence():
    defs = DEFS + "fam DUPONT Jean.1 +1901 MARTIN Zoe\n"
    g = _notes("DUPONT Jean.1", "Texte", defs)
    assert g.persons["DUPONT_Jean_1"].notes == ["Texte"]
    assert g.persons["DUPONT_Jean_0"].notes == []


@pytest.mark.parametrize(
    ("header", "pid"),
    [
        ('MARTIN Anne_"Dit".2', 'MARTIN_Anne_"Dit"_2'),
        ("DE/_B Anne", "DE/_B_Anne_0"),
    ],
)
def test_entete_compose(header, pid):
    g = _notes(header, "Texte")
    assert g.persons[pid].notes == ["Texte"]


def test_notes_suivies_dun_autre_bloc():
    g = GeneWebParser(validate=False).parse_string(
        DEFS + "notes DUPONT Jean\nbeg\nA\nB\nend notes\n"
        "notes MARTIN Anne\nbeg\nC\nend notes\n"
    )
    assert g.persons["DUPONT_Jean_0"].notes == ["A\nB"]
    assert g.persons["MARTIN_Anne_0"].notes == ["C"]
