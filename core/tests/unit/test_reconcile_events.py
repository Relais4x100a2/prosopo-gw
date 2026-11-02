"""Réconciliation lignes / blocs d'événements, comme ``gwc`` (fevt, pevt)."""

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.event import FamilyEventType
from geneweb_py.core.family import FamilyQualifier, MarriageStatus


def _parse(texte, mode, tmp_path):
    if mode == "complet":
        return GeneWebParser(validate=False).parse_string(texte)
    fichier = tmp_path / "base.gw"
    fichier.write_text(texte, encoding="utf-8")
    return GeneWebParser(validate=False, stream_mode=True).parse_file(str(fichier))


def _famille(texte, mode, tmp_path):
    (f,) = _parse(texte, mode, tmp_path).families.values()
    return f


def _types(famille):
    return [e.family_event_type for e in famille.events]


pytestmark = pytest.mark.parametrize("mode", ["complet", "streaming"])


def test_ligne_fam_fabrique_le_mariage(mode, tmp_path):
    f = _famille(
        "fam DUPONT Jean +1900 #mp Ville MARTIN Anne #ms Acte_1\n", mode, tmp_path
    )
    (mariage,) = f.events
    assert mariage.family_event_type is FamilyEventType.MARRIAGE
    assert (mariage.date.year, mariage.place, mariage.source) == (
        1900,
        "Ville",
        "Acte 1",
    )
    assert mariage.metadata["synthesized"] is True
    assert f.metadata["events_synthesized"] is True


@pytest.mark.parametrize(
    ("ligne", "attendu"),
    [
        ("fam A B +1900 #noment C D", FamilyEventType.NO_MENTION),
        ("fam A B +1900 #nm C D", FamilyEventType.NO_MARRIAGE),
        ("fam A B +1900 #eng C D", FamilyEventType.ENGAGEMENT),
        ("fam A B +1900 #banns C D", FamilyEventType.MARRIAGE_BANN),
        ("fam A B +1900 #pacs C D", FamilyEventType.PACS),
    ],
)
def test_type_de_l_evenement_fabrique(ligne, attendu, mode, tmp_path):
    assert _types(_famille(ligne + "\n", mode, tmp_path))[0] is attendu


def test_divorce_fabrique_apres_le_mariage(mode, tmp_path):
    f = _famille("fam A B +1900 -1950 C D\n", mode, tmp_path)
    assert _types(f) == [FamilyEventType.MARRIAGE, FamilyEventType.DIVORCE]
    assert f.events[1].date.year == 1950


def test_le_bloc_fevt_fait_foi_et_le_dernier_mariage_gagne(mode, tmp_path):
    f = _famille(
        "fam A B +1800 #mp Ancien C D\nfevt\n#marr 1850 #p Premier\n"
        "#marr 1860 #p Dernier\nend fevt\n",
        mode,
        tmp_path,
    )
    assert f.marriage_date.year == 1860
    assert f.marriage_place == "Dernier"
    assert [e.date.year for e in f.events] == [1850, 1860]
    assert "events_synthesized" not in f.metadata


def test_fevt_nmen_donne_le_type_et_le_lieu(mode, tmp_path):
    f = _famille("fam A B + C D\nfevt\n#nmen 1850 #p Ville\nend fevt\n", mode, tmp_path)
    assert f.marriage_status is MarriageStatus.MARRIED
    assert f.family_qualifiers == [FamilyQualifier.NO_MENTION]
    assert f.marriage_place == "Ville"


def test_fevt_contrat_recopie_vers_sans_lieu(mode, tmp_path):
    f = _famille("fam A B + C D\nfevt\n#marc 1850 #p Etude\nend fevt\n", mode, tmp_path)
    assert f.marriage_date.prefix.value == "~"
    assert f.marriage_place is None


def test_fevt_divorce_est_recopie(mode, tmp_path):
    f = _famille(
        "fam A B + C D\nfevt\n#marr 1850\n#div 1860\nend fevt\n", mode, tmp_path
    )
    assert f.marriage_status is MarriageStatus.DIVORCED
    assert f.divorce_date.year == 1860


def test_personne_sans_pevt_recoit_ses_evenements(mode, tmp_path):
    g = _parse(
        "fam DUPONT Jean 1/1/1900 #bp Ville_A #bs Reg 2/2/1970 #dp Ville_B + MARTIN Anne\n",
        mode,
        tmp_path,
    )
    p = g.persons["DUPONT_Jean_0"]
    assert [e.event_type.value for e in p.events] == ["birt", "deat"]
    assert p.events[0].place == "Ville A" and p.events[0].source == "Reg"
    assert p.metadata["events_synthesized"] is True


def test_personne_sans_donnee_n_a_pas_d_evenement(mode, tmp_path):
    g = _parse("fam DUPONT Jean + MARTIN Anne\n", mode, tmp_path)
    p = g.persons["DUPONT_Jean_0"]
    assert p.events == []
    assert "events_synthesized" not in p.metadata


def test_pevt_le_premier_evenement_fait_foi(mode, tmp_path):
    g = _parse(
        "fam DUPONT Jean + MARTIN Anne\n\npevt DUPONT Jean\n"
        "#birt 1900 #p Premier\n#birt 1901 #p Second\nend pevt\n",
        mode,
        tmp_path,
    )
    p = g.persons["DUPONT_Jean_0"]
    assert (p.birth_date.year, p.birth_place) == (1900, "Premier")
    assert "events_synthesized" not in p.metadata
