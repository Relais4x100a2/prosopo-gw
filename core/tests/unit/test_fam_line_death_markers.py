"""Marqueurs de décès ``od`` / ``mj`` (nus ou ``#od``) sur la ligne fam.

Mal lus, ils devenaient le nom de l'épouse : elle disparaissait. Données synthétiques.
"""

import pytest

from geneweb_py import GeneWebParser


def _parse(texte: str):  # type: ignore[no-untyped-def]
    return GeneWebParser(validate=False).parse_string(texte)


@pytest.mark.parametrize("marqueur", ["od", "#od", "mj", "#mj"])
@pytest.mark.parametrize("date", ["0", "1900"])
def test_marqueur_deces_du_mari_ne_masque_pas_l_epouse(
    marqueur: str, date: str
) -> None:
    g = _parse(f"fam DUPONT Paul {date} {marqueur} + MARTIN Anne\n")
    (f,) = g.families.values()
    assert (f.husband_id, f.wife_id) == ("DUPONT_Paul_0", "MARTIN_Anne_0")


def test_marqueurs_apubl_0_od_des_deux_conjoints() -> None:
    g = _parse("fam DUPONT Paul #apubl 0 od + MARTIN Anne #apubl 0 od\n")
    (f,) = g.families.values()
    assert (f.husband_id, f.wife_id) == ("DUPONT_Paul_0", "MARTIN_Anne_0")


def test_marqueurs_sont_conserves_sur_chaque_personne() -> None:
    g = _parse("fam DUPONT Paul 0 od + MARTIN Anne 1900 mj\n")
    assert g.persons["DUPONT_Paul_0"].is_obviously_dead is True
    assert g.persons["DUPONT_Paul_0"].is_young_death is False
    assert g.persons["MARTIN_Anne_0"].is_young_death is True
    assert g.persons["MARTIN_Anne_0"].is_obviously_dead is False


def test_od_suivi_d_une_date_de_deces() -> None:
    g = _parse("fam DUPONT Paul 1800 #od 1850 + MARTIN Anne\n")
    p = g.persons["DUPONT_Paul_0"]
    assert p.is_obviously_dead is True
    assert str(p.death_date) == "1850"


def test_nom_ou_prenom_od_reste_un_nom() -> None:
    g = _parse("fam od Paul + MARTIN od\n")
    (f,) = g.families.values()
    assert (f.husband_id, f.wife_id) == ("od_Paul_0", "MARTIN_od_0")
