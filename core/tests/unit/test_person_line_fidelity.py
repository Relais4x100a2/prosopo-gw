"""Lignes de personne dans ``fam`` (parents et enfants) : dates, lieux et sources."""

from geneweb_py import GeneWebParser


def _persons(texte: str):
    return GeneWebParser(validate=False).parse_string(texte).persons


def _d(date):
    return None if date is None else date.raw_text


def test_enfant_date_de_naissance_seule():
    p = _persons("fam DUPONT Paul +1750 MARTIN Anne\nbeg\n- f Marie 1753\nend\n")
    assert _d(p["DUPONT_Marie_0"].birth_date) == "1753"


def test_enfant_naissance_bapteme_deces_avec_lieux_et_sources():
    p = _persons(
        "fam DUPONT Paul +1750 MARTIN Anne\nbeg\n"
        "- h Luc 3/3/1751 #bp [Moulin]_-_Dreux #bs Reg_N !5/3/1751 #pp Chartres #ps Reg_B "
        "1790 #dp Dreux #ds Reg_D\nend\n"
    )["DUPONT_Luc_0"]
    assert _d(p.birth_date) == "3/3/1751"
    assert p.birth_place == "[Moulin] - Dreux"
    assert p.birth_source == "Reg N"
    assert _d(p.baptism_date) == "5/3/1751"
    assert (p.baptism_place, p.baptism_source) == ("Chartres", "Reg B")
    assert _d(p.death_date) == "1790"
    assert (p.death_place, p.death_source) == ("Dreux", "Reg D")


def test_enfant_naissance_inconnue_puis_deces():
    p = _persons("fam DUPONT Paul +1750 MARTIN Anne\nbeg\n- Jean 0 1790\nend\n")[
        "DUPONT_Jean_0"
    ]
    assert _d(p.death_date) == "1790"


def test_parent_sur_la_ligne_fam_garde_ses_dates_et_l_epouse():
    g = GeneWebParser(validate=False).parse_string(
        "fam DUPONT Paul 1720 #bp Dreux #bs Reg_1 !1721 #pp Chartres 1790 #dp Chartres "
        "+1750 MARTIN Anne 1725\n"
    )
    p = g.persons["DUPONT_Paul_0"]
    assert _d(p.birth_date) == "1720" and p.birth_place == "Dreux"
    assert _d(p.baptism_date) == "1721" and p.baptism_place == "Chartres"
    assert _d(p.death_date) == "1790" and p.death_place == "Chartres"
    (fam,) = g.families.values()
    assert _d(fam.marriage_date) == "1750"
    assert fam.wife_id == "MARTIN_Anne_0"
    assert _d(g.persons["MARTIN_Anne_0"].birth_date) == "1725"


def test_les_dates_de_la_ligne_src_ne_vont_pas_a_l_epouse():
    p = _persons(
        "fam MARTIN Pierre +1705 DUBOIS Marie\nsrc BMS Saint-Aubin 1705-1715\n"
    )["DUBOIS_Marie_0"]
    assert p.birth_date is None and p.death_date is None


def test_source_url_est_un_seul_mot_et_ne_fuit_pas_en_date():
    p = _persons(
        "fam DUPONT Paul +1750 MARTIN Anne\nbeg\n"
        "- h Luc 1751 #bs http://exemple.org/a?x=1&y=2 1790 #dp Dreux\nend\n"
    )["DUPONT_Luc_0"]
    assert p.birth_source == "http://exemple.org/a?x=1&y=2"
    assert _d(p.death_date) == "1790" and p.death_place == "Dreux"


def test_lieu_avec_balises_html_collees_reste_un_seul_mot():
    p = _persons(
        "fam DUPONT Paul +1750 MARTIN Anne\nbeg\n"
        "- h Luc 1751 #bp [Eglise]_-_Dreux<br>Chartres 1790\nend\n"
    )["DUPONT_Luc_0"]
    assert p.birth_place == "[Eglise] - Dreux<br>Chartres"
    assert _d(p.birth_date) == "1751" and _d(p.death_date) == "1790"
