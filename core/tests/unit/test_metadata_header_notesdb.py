"""En-tête (encoding:, gwplus) et bloc notes-db : métadonnées fidèles au fichier."""

from geneweb_py import GeneWebParser

BASE = "fam A B +1900 C D\nbeg\n- h X\nend\n"


def _parse(s):
    return GeneWebParser(validate=False).parse_string(s)


def test_entete_gwplus_et_encoding():
    g = _parse("encoding: utf-8\ngwplus\n\n" + BASE)
    assert g.metadata.is_gwplus is True
    assert g.metadata.encoding == "utf-8"


def test_sans_entete_valeurs_par_defaut():
    g = _parse(BASE)
    assert g.metadata.is_gwplus is False
    assert g.metadata.encoding == "iso-8859-1"


def test_notes_db_verbatim():
    texte = (
        "  TITLE=Un titre\n\n  '''Gras'''\n  *Item : [[A/B]], [[C/D]]\n  *Autre  \"x\""
    )
    g = _parse(f"notes-db\n{texte}\nend notes-db\n\n" + BASE)
    assert g.metadata.database_notes == [texte]
