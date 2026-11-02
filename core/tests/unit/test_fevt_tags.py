"""Tags d'événements familiaux autres que marr/div/sep/enga dans un bloc fevt."""

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.event import FamilyEventType

_BASE = "fam MARTIN Pierre +1705 DUBOIS Marie\nfevt\n"


def _evts(corps: str):
    g = GeneWebParser(validate=False).parse_string(_BASE + corps + "end fevt\n")
    return [e for f in g.families.values() for e in f.events]


@pytest.mark.parametrize(
    "tag,attendu",
    [
        ("marc", FamilyEventType.MARRIAGE_CONTRACT),
        ("marb", FamilyEventType.MARRIAGE_BANN),
        ("marl", FamilyEventType.MARRIAGE_LICENSE),
        ("nmar", FamilyEventType.NO_MARRIAGE),
        ("nmen", FamilyEventType.NO_MENTION),
        ("anul", FamilyEventType.ANNULMENT),
        ("pacs", FamilyEventType.PACS),
        ("resi", FamilyEventType.RESIDENCE),
    ],
)
def test_tag_familial_standard_devient_un_evenement_complet(tag, attendu):
    (e,) = _evts(
        f"#{tag} 1704 #p Lyon #s Reg\nwit m: LEROY Paul\nwnote tel\nnote une note\n"
    )
    assert e.family_event_type == attendu
    assert str(e.date) == "1704"
    assert e.place == "Lyon"
    assert e.source == "Reg"
    assert len(e.witnesses) == 1 and e.witnesses[0]["note"] == "tel"
    assert e.notes == ["une note"]


def test_tag_personnalise_est_capture_en_type_libre():
    (e,) = _evts("#Hypotheque 1704 #p Lyon\n")
    assert e.family_event_type == FamilyEventType.OTHER
    assert e.event_type_raw == "Hypotheque"
    assert str(e.date) == "1704" and e.place == "Lyon"


def test_evenements_standard_et_autres_gardent_l_ordre_du_bloc():
    evts = _evts("#marc 1704\n#marr 1705\n#resi 1706\n")
    assert [e.family_event_type for e in evts] == [
        FamilyEventType.MARRIAGE_CONTRACT,
        FamilyEventType.MARRIAGE,
        FamilyEventType.RESIDENCE,
    ]


def test_famille_sans_aucun_conjoint_connu_garde_enfants_et_evenements():
    g = GeneWebParser(validate=False).parse_string(
        "fam ? ? + ? ?\nbeg\n- h Pierre 1700\nend\nfevt\n#marr 1699\nend fevt\n"
    )
    (f,) = g.families.values()
    assert (f.husband_id, f.wife_id) == ("?_?_0", "?_?_1")
    assert len(f.children) == 1
    assert [e.family_event_type for e in f.events] == [FamilyEventType.MARRIAGE]
    assert f.validation_errors == []
    assert len(g.persons) == 3
    assert [p.is_anonymous for p in g.persons.values()].count(True) == 2


def test_fevt_apres_famille_sans_conjoint_ne_se_rattache_pas_a_la_famille_precedente():
    g = GeneWebParser(validate=False).parse_string(
        "fam MARTIN Pierre + DUBOIS Marie\nfam ? ? + ? ?\nfevt\n#marr 1699\nend fevt\n"
    )
    premiere, seconde = g.families.values()
    assert premiere.events == []
    assert len(seconde.events) == 1
