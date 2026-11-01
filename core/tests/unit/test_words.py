"""Lecture par mots bruts (``words.py``) : découpage, décodage et partie mariage."""

import pytest

from geneweb_py.core.parser.words import (
    MarriagePart,
    cut_space,
    decode_word,
    read_marriage_part,
    split_words,
    word_spans,
)


def test_split_words_garde_les_mots_bruts():
    ligne = 'fam  A B\t+1/2/1900 #ms Acte_"copie"_n°3/12 C D'
    assert split_words(ligne) == [
        "fam",
        "A",
        "B",
        "+1/2/1900",
        "#ms",
        'Acte_"copie"_n°3/12',
        "C",
        "D",
    ]


def test_word_spans_donne_les_positions():
    assert word_spans("ab  c") == [("ab", 0), ("c", 4)]


@pytest.mark.parametrize(
    ("mot", "valeur"),
    [
        ("Ville,_80000", "Ville, 80000"),
        (r"A\_B", "A_B"),
        ("fin_", "fin "),
        ("x\\", "x\\"),
        ("", ""),
    ],
)
def test_decode_word(mot, valeur):
    assert decode_word(mot) == valeur


@pytest.mark.parametrize(
    ("texte", "attendu"), [(" a b ", "a b"), (" ", ""), ("", ""), ("ab", "ab")]
)
def test_cut_space(texte, attendu):
    assert cut_space(texte) == attendu


def _lire(ligne: str, dates=()):
    mots = split_words(ligne)
    part, fin = read_marriage_part(mots, 0, lambda k: mots[k] in dates)
    return part, mots[fin:]


def test_partie_mariage_complete_dans_l_ordre_de_gwc():
    part, reste = _lire(
        "+1/2/1900 #noment mf #mp Ville,_80000 #mn Note #ms 3_E_041/472 -1910 C D"
    )
    assert part == MarriagePart(
        date="1/2/1900",
        relations=["noment"],
        sexes="mf",
        place="Ville,_80000",
        note="Note",
        source="3_E_041/472",
        divorced=True,
        divorce_date="1910",
    )
    assert reste == ["C", "D"]


def test_plus_seul_sans_rien():
    part, reste = _lire("+ C D")
    assert part == MarriagePart()
    assert reste == ["C", "D"]


@pytest.mark.parametrize("tag", ["nm", "eng"])
def test_relation_sans_code(tag):
    part, reste = _lire(f"+ #{tag} mf D")
    assert part.relations == [tag]
    assert part.sexes is None
    assert reste == ["mf", "D"]


@pytest.mark.parametrize(
    "tag",
    ["noment", "nsck", "nsckm", "banns", "contract", "license", "pacs", "residence"],
)
@pytest.mark.parametrize("code", ["mf", "ff", "m?", "??"])
def test_relation_avec_code_de_sexe(tag, code):
    part, reste = _lire(f"+1900 #{tag} {code} C D")
    assert part.relations == [tag]
    assert part.sexes == code
    assert reste == ["C", "D"]


def test_relation_sans_code_reste_lue():
    # gwc exige un code après #nsck… ; on reste tolérant : le nom suit
    part, reste = _lire("+ #residence C D")
    assert part.relations == ["residence"]
    assert part.sexes is None
    assert reste == ["C", "D"]


def test_code_de_sexe_invalide_est_rendu():
    part, reste = _lire("+ #noment MF Anne")
    assert part.relations == ["noment"]
    assert part.sexes is None
    assert reste == ["MF", "Anne"]


@pytest.mark.parametrize(
    ("ligne", "divorce", "date"),
    [("+ - C D", True, None), ("+ -<1974 C D", True, "<1974")],
)
def test_divorce(ligne, divorce, date):
    part, reste = _lire(ligne)
    assert (part.divorced, part.divorce_date) == (divorce, date)
    assert reste == ["C", "D"]


def test_separation():
    part, reste = _lire("+1900 #sep C D")
    assert part.separated is True
    assert reste == ["C", "D"]


def test_tolerances_dates_detachees():
    # ``+ date``, ``- date``, ``#sep date`` et ``#div date`` : tolérances historiques
    part, reste = _lire(
        "+ 1/1/1900 #sep 1/1/1905 #div 1/1/1910 C D",
        dates=("1/1/1900", "1/1/1905", "1/1/1910"),
    )
    assert part.date == "1/1/1900"
    assert part.separated and part.separation_date == "1/1/1905"
    assert part.divorced and part.divorce_date == "1/1/1910"
    assert reste == ["C", "D"]
    part, reste = _lire("+1750 #mp V - 1760 C D", dates=("1760",))
    assert (part.divorced, part.divorce_date, reste) == (True, "1760", ["C", "D"])


@pytest.mark.parametrize(
    ("ligne", "divorce"), [("+ #sep - C D", False), ("+ #div - C D", True)]
)
def test_tiret_apres_sep_ou_div_vaut_date_absente(ligne, divorce):
    part, reste = _lire(ligne)
    assert part.divorced is divorce
    assert part.divorce_date is None and part.separation_date is None
    assert reste == ["C", "D"]


def test_date_detachee_seulement_si_c_est_une_date():
    part, reste = _lire("+ - ? ?")
    assert (part.divorced, part.divorce_date, reste) == (True, None, ["?", "?"])


def test_ordre_libre_des_marqueurs():
    part, reste = _lire("+ #sep #nm C D")
    assert part.relations == ["nm"] and part.separated
    assert reste == ["C", "D"]


def test_champ_sans_valeur_en_fin_de_ligne():
    part, reste = _lire("+1900 #ms")
    assert part.source is None
    assert reste == []


def test_le_premier_mot_doit_commencer_par_plus():
    with pytest.raises(ValueError):
        read_marriage_part(["C", "D"], 0)
