"""Lignes de texte libre (note, comm, src, texte nu) : conservées telles quelles."""

from geneweb_py import GeneWebParser

TEXTE = 'Il dit "oui"  et  wit puis marr, birt (p. 3) <br> fin'


def _parse(s):
    return GeneWebParser(validate=False).parse_string(s)


def test_note_evenement_familial():
    g = _parse(
        f"fam A B +1900 C D\nfevt\n#marr 1900\nnote {TEXTE}\nend fevt\nbeg\n- h X\nend\n"
    )
    (f,) = g.families.values()
    assert f.events[0].notes == [TEXTE]


def test_note_evenement_personnel():
    g = _parse(f"pevt A B\n#birt 1900\nnote {TEXTE}\nnote deux\nend pevt\n")
    assert g.persons["A_B_0"].events[0].notes == [TEXTE, "deux"]


def test_commentaire_et_source_de_famille():
    g = _parse(
        f'fam A B +1900 C D\nsrc Livre "x"  p. 3 wit\ncomm {TEXTE}\nbeg\n- h X\nend\n'
    )
    (f,) = g.families.values()
    assert f.family_source == 'Livre "x"  p. 3 wit'
    assert f.comments == [TEXTE]


def test_texte_nu_apres_comm():
    g = _parse('fam A B +1900 C D\ncomm L1\nTexte nu "q"  deux\nbeg\n- h X\nend\n')
    (f,) = g.families.values()
    assert f.comments == ['L1\nTexte nu "q"  deux']


def test_note_evenement_marie_sans_perdre_la_suite():
    g = _parse(
        "fam A B +1900 C D\nfevt\n#marr 1900\nnote a wit b\n#resi 1910\nnote c\n"
        "end fevt\nbeg\n- h X\nend\n"
    )
    (f,) = g.families.values()
    assert [e.notes for e in f.events] == [["a wit b"], ["c"]]


def test_notes_vides_et_espace_en_fin_de_ligne():
    g = _parse(
        "fam A B +1900 C D\nfevt\n#resi 1926\nwit f: X Y\nnote a  b\nnote \n"
        "note Jacques W, med (hab 30), ami.\nnote \nnote en 1936 : http://x.fr/a\n"
        "#marr 1900\nend fevt\nbeg\n- h Z\nend\n"
    )
    (f,) = g.families.values()
    assert f.events[0].notes == [
        "a  b",
        "",
        "Jacques W, med (hab 30), ami.",
        "",
        "en 1936 : http://x.fr/a",
    ]


def test_espace_en_fin_de_ligne_donne_un_newline():
    from geneweb_py.core.parser.lexical import LexicalParser, TokenType

    types = [t.type for t in LexicalParser("note \nnote x\n").tokenize()]
    assert TokenType.UNKNOWN not in types
    assert types.count(TokenType.NEWLINE) == 2
