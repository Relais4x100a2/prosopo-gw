"""Qualificatif d'union (et code de sexe) placé avant le ``+`` : l'épouse n'est plus perdue."""

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.family import FamilyQualifier

CAS = [
    ("#banns mf +", None, FamilyQualifier.BANNS),
    ("#banns +", None, FamilyQualifier.BANNS),
    ("#pacs +", None, FamilyQualifier.PACS),
    ("#pacs mf +", None, FamilyQualifier.PACS),
    ("#residence ff +1900", "1900", FamilyQualifier.RESIDENCE),
    ("#noment mf +1900 #mp V", "1900", FamilyQualifier.NO_MENTION),
    ("+1900 #pacs mf", "1900", FamilyQualifier.PACS),
    ("#nsck +", None, FamilyQualifier.NO_SEX_CHECK),
]


@pytest.mark.parametrize("mode", ["complet", "streaming"])
@pytest.mark.parametrize("morceau,date,qualif", CAS)
def test_qualificatif_avant_le_plus(morceau, date, qualif, mode, tmp_path):
    texte = f"fam DUPONT Jean {morceau} MARTIN Anne\n"
    if mode == "complet":
        g = GeneWebParser(validate=False).parse_string(texte)
    else:
        fichier = tmp_path / "base.gw"
        fichier.write_text(texte, encoding="utf-8")
        g = GeneWebParser(validate=False, stream_mode=True).parse_file(str(fichier))
    (f,) = g.families.values()
    assert f.husband_id == "DUPONT_Jean_0"
    assert f.wife_id == "MARTIN_Anne_0"
    assert (str(f.marriage_date) if f.marriage_date else None) == date
    assert f.family_qualifiers == [qualif]
