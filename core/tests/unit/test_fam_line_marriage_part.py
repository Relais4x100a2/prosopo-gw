"""Partie mariage de la ligne fam lue mot à mot (``+date``, relation, #mp, #ms, divorce)."""

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.family import FamilyQualifier, MarriageStatus
from geneweb_py.core.parser.lexical import LexicalParser
from geneweb_py.core.parser.words import cut_space, decode_word


def _famille(ligne: str, tmp_path=None):
    texte = ligne + "\n"
    if tmp_path is None:
        g = GeneWebParser(validate=False).parse_string(texte)
    else:
        fichier = tmp_path / "base.gw"
        fichier.write_text(texte, encoding="utf-8")
        g = GeneWebParser(validate=False, stream_mode=True).parse_file(str(fichier))
    (f,) = g.families.values()
    return f


SOURCES = {
    "slash": "3_E_041/472",
    "guillemets": '_<a_class="visio"_href="https://x.example/v?id=1">Lien</a>',
    "date": "1/2/1900_acte_12",
}


@pytest.mark.parametrize("mode", ["complet", "streaming"])
@pytest.mark.parametrize("source", SOURCES.values(), ids=SOURCES.keys())
def test_source_de_mariage_lue_telle_quelle(source, mode, tmp_path):
    f = _famille(
        f"fam DUPONT Jean +1/2/1900 #mp Ville,_80000 #ms {source} MARTIN Anne",
        tmp_path if mode == "streaming" else None,
    )
    assert f.marriage_source == cut_space(decode_word(source))
    assert f.marriage_place == "Ville, 80000"
    assert f.wife_id == "MARTIN_Anne_0"


def test_lieu_de_mariage_avec_guillemets_garde_le_mot_brut():
    f = _famille('fam DUPONT Jean +1900 #mp Le_"Clos"_-_Ville MARTIN Anne')
    assert f.marriage_place == 'Le "Clos" - Ville'


def test_qualificatif_apres_la_source_du_mari():
    f = _famille("fam DUPONT Jean #src Reg + #noment mf MARTIN Anne #src Reg")
    assert f.family_qualifiers == [FamilyQualifier.NO_MENTION]
    assert f.wife_id == "MARTIN_Anne_0"


def test_source_de_mariage_apres_la_source_du_mari():
    f = _famille("fam DUPONT Jean #src Reg +1900 #ms Acte_12 MARTIN Anne")
    assert f.marriage_source == "Acte 12"


@pytest.mark.parametrize(
    ("tag", "qualificatif"),
    [
        ("noment", FamilyQualifier.NO_MENTION),
        ("nsck", FamilyQualifier.NO_SEX_CHECK),
        ("nsckm", FamilyQualifier.NO_SEX_CHECK_MARRIAGE),
        ("banns", FamilyQualifier.BANNS),
        ("contract", FamilyQualifier.CONTRACT),
        ("license", FamilyQualifier.LICENSE),
        ("pacs", FamilyQualifier.PACS),
        ("residence", FamilyQualifier.RESIDENCE),
    ],
)
def test_qualificatif_lu_une_seule_fois(tag, qualificatif):
    f = _famille(f"fam DUPONT Jean +1900 #{tag} mf #mp V MARTIN Anne")
    assert f.family_qualifiers == [qualificatif]
    assert f.marriage_place == "V"


def test_qualificatif_avant_le_plus_reste_lu():
    # Ordre hors grammaire gwc, accepté par tolérance (tests historiques)
    f = _famille("fam DUPONT Jean #banns #contract + MARTIN Marie")
    assert f.family_qualifiers == [FamilyQualifier.BANNS, FamilyQualifier.CONTRACT]


@pytest.mark.parametrize("mode", ["complet", "streaming"])
@pytest.mark.parametrize(
    ("tag", "qualificatif"),
    [("pacs", FamilyQualifier.PACS), ("residence", FamilyQualifier.RESIDENCE)],
)
def test_pacs_et_residence_sont_des_qualificatifs(tag, qualificatif, mode, tmp_path):
    f = _famille(
        f"fam DUPONT Jean +1858 #{tag} ff #mp _[rue_X]_-_Ville MARTIN Anne",
        tmp_path if mode == "streaming" else None,
    )
    assert f.family_qualifiers == [qualificatif]
    assert f.marriage_place == "[rue X] - Ville"
    assert f.wife_id == "MARTIN_Anne_0"


def test_date_de_mariage_texte_avec_soulignes():
    f = _famille("fam DUPONT Jean +0(20_mars_1805) MARTIN Anne")
    assert f.marriage_date is not None
    assert f.marriage_date.text_date == "20_mars_1805"


def test_note_de_mariage_n_est_pas_l_epouse():
    f = _famille("fam DUPONT Jean +1900 #mp V #mn Note_de_mariage MARTIN Anne")
    assert f.wife_id == "MARTIN_Anne_0"


def test_separation_puis_divorce_dates_detachees():
    f = _famille("fam A B + #mp Lyon #sep 15/06/1985 #div 01/09/1988 C D")
    assert f.marriage_status == MarriageStatus.DIVORCED
    assert f.is_separated is True
    assert str(f.divorce_date) == "01/09/1988"
    assert f.wife_id == "C_D_0"


def test_sans_texte_source_les_mots_viennent_des_jetons():
    # API avancée (MultiPassParser sans contenu) : pas de texte source
    ligne = 'fam DUPONT Jean +1900 #noment mf #ms 3_E_041/472 MARTIN Anne"Dit"\n'
    parser = GeneWebParser(validate=False)
    parser._source = None
    info = parser._parse_family_line(LexicalParser(ligne).tokenize())
    assert info["marriage_source"] == "3 E 041/472"
    assert info["family_qualifiers"] == [FamilyQualifier.NO_MENTION]
    assert (info["wife_name"], info["wife_firstname"]) == ("MARTIN", 'Anne"Dit"')
