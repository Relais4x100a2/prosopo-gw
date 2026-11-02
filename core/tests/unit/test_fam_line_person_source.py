"""Source de personne ``#src`` sur la ligne fam : source du conjoint, pas de la famille."""

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.parser.lexical import LexicalParser
from geneweb_py.core.parser.words import cut_space, decode_word


def _base(texte: str, tmp_path=None):
    if tmp_path is None:
        return GeneWebParser(validate=False).parse_string(texte)
    fichier = tmp_path / "base.gw"
    fichier.write_text(texte, encoding="utf-8")
    return GeneWebParser(validate=False, stream_mode=True).parse_file(str(fichier))


def _famille(ligne: str):
    return list(_base(ligne + "\n").families.values())[0]


@pytest.mark.parametrize(
    "source", ["Reg", "Reg(Pa", "Reg(Pa)", "https://www.example.org/a?x=1&y=2"]
)
def test_source_de_personne_du_mari_avant_le_plus(source):
    g = _base(f"fam DUPONT Jean #src {source} + #noment mf MARTIN Anne #src {source}\n")
    (f,) = g.families.values()
    assert f.husband_id == "DUPONT_Jean_0"
    assert f.wife_id == "MARTIN_Anne_0"
    assert g.persons["DUPONT_Jean_0"].person_source == source
    assert g.persons["MARTIN_Anne_0"].person_source == source


def test_source_de_personne_du_mari_sans_qualificatif():
    f = _famille("fam DUPONT Jean #apubl #src Reg + MARTIN Anne #apubl #src Reg")
    assert f.wife_id == "MARTIN_Anne_0"


SOURCES = {
    "slash": "3_E_041/472",
    "guillemets": '_<a_class="visio"_href="https://x.example/v?id=1">Lien</a>',
    "echappement": r"https://x.example/wiki/A\_B\_(1849%E2%80%931928)",
}


@pytest.mark.parametrize("mode", ["complet", "streaming"])
@pytest.mark.parametrize("source", SOURCES.values(), ids=SOURCES.keys())
def test_source_des_conjoints_decodee_comme_gwc(source, mode, tmp_path):
    g = _base(
        f"fam DUPONT Jean #src Reg_1 +1900 #mp V MARTIN Anne #src {source}\n",
        tmp_path if mode == "streaming" else None,
    )
    (f,) = g.families.values()
    assert g.persons["DUPONT_Jean_0"].person_source == "Reg 1"
    assert g.persons["MARTIN_Anne_0"].person_source == cut_space(decode_word(source))
    assert f.family_source is None
    assert f.marriage_place == "V"


def test_source_de_l_epouse_seule():
    g = _base("fam DUPONT Jean +1900 MARTIN Anne #src Acte_12\n")
    (f,) = g.families.values()
    assert g.persons["DUPONT_Jean_0"].person_source is None
    assert g.persons["MARTIN_Anne_0"].person_source == "Acte 12"
    assert f.family_source is None


@pytest.mark.parametrize("mode", ["complet", "streaming"])
def test_ligne_src_reste_la_source_de_famille(mode, tmp_path):
    g = _base(
        "fam DUPONT Jean #src Reg + MARTIN Anne\nsrc Registre_paroissial\n"
        "beg\n- h Paul\nend\n",
        tmp_path if mode == "streaming" else None,
    )
    (f,) = g.families.values()
    assert f.family_source == "Registre_paroissial"
    assert g.persons["DUPONT_Jean_0"].person_source == "Reg"
    assert g.persons["MARTIN_Anne_0"].person_source is None


def test_sans_texte_source_le_mot_vient_des_jetons():
    # API avancée (MultiPassParser sans contenu) : pas de texte source
    ligne = "fam DUPONT Jean #src 3_E_041/472 + MARTIN Anne #src Reg(Pa)\n"
    parser = GeneWebParser(validate=False)
    parser._source = None
    info = parser._parse_family_line(LexicalParser(ligne).tokenize())
    assert info["husband_person_source"] == "3 E 041/472"
    assert info["wife_person_source"] == "Reg(Pa)"
    assert (info["wife_name"], info["wife_firstname"]) == ("MARTIN", "Anne")


@pytest.mark.parametrize(
    "source",
    [
        "Reg",
        "https://x.example/a?b=c&d=e",
        r"https://x.example/wiki/A\_B\_(1849%E2%80%931928)",
        "3_E_041/472",
    ],
)
def test_source_du_temoin_est_un_seul_mot(source):
    g = GeneWebParser(validate=False).parse_string(
        f"fam A B +1900 C D\nwit m: P Q #occu x #src {source} 22/7/1849 #bp V\n"
        "wit m: R S\nwit m: T U\nbeg\n- h X\nend\n"
    )
    (f,) = g.families.values()
    assert [w["person_id"] for w in f.witnesses] == ["P_Q_0", "R_S_0", "T_U_0"]
    assert g.persons["P_Q_0"].birth_place == "V"
    assert f.family_source is None
