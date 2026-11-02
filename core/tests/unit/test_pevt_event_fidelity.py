"""Fidélité des événements ``pevt`` / ``fevt`` : aucun événement ne doit être perdu.

Fixtures 100 % synthétiques. Couvre quatre défauts historiques :
tags personnalisés avec ``_``/``-``/chiffres, tags standard perdus (``occu``, ``buri``,
``crem``), notes non rattachées aux événements, lieux ``[complément]_-_lieu`` bruts.
"""

import pytest

from geneweb_py.core.event import EventType
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.place import ParsedPlace, parse_place

HEADER = "encoding: utf-8\ngwplus\n\n"

# Tags de personnes (hors familiaux) reconnus par GeneWeb pour les événements personnels
STANDARD_TAGS = [
    "birt", "bapt", "deat", "buri", "crem", "acco", "acqu", "adhe", "bapl", "barm",
    "basm", "bles", "cens", "chgn", "circ", "conf", "conl", "degr", "awar", "demm",
    "dist", "endl", "dotl", "educ", "elec", "emig", "exco", "flkl", "fcom", "fune",
    "grad", "hosp", "illn", "immi", "lpas", "mdis", "mpro", "mser", "mobm", "natu",
    "occu", "ordn", "prop", "resi", "reti", "slgc", "slgp", "slgs", "vteb", "will",
]  # fmt: skip


def _pevt_events(body: str):
    """Parse un bloc ``pevt`` de DUPONT Jean et renvoie ses événements."""
    genealogy = GeneWebParser().parse_string(
        HEADER + "pevt DUPONT Jean\n" + body + "end pevt\n"
    )
    person = next(p for p in genealogy.persons.values() if p.last_name == "DUPONT")
    return person.events, person


class TestCustomTagsWithSpecialCharacters:
    """Défaut 1 : tags personnalisés (``#strng``) avec ``_``, ``-`` et chiffres."""

    @pytest.mark.parametrize(
        "tag",
        ["Cours_peinture", "Membre_1900", "Action-Sociale", "a_b-c_9", "X1"],
    )
    def test_tag_is_kept_in_full(self, tag):
        events, _ = _pevt_events(f"#{tag} 1990 #p Lyon\n")
        assert len(events) == 1
        assert events[0].event_type == EventType.OTHER
        assert events[0].event_type_raw == tag
        assert events[0].place == "Lyon"
        assert str(events[0].date) == "1990"

    def test_tag_without_date_nor_place(self):
        events, _ = _pevt_events("#Cours_peinture\n")
        assert [e.event_type_raw for e in events] == ["Cours_peinture"]

    def test_several_custom_events_keep_order_and_witnesses(self):
        events, _ = _pevt_events(
            "#Cours_peinture ~1990\nwit m: MARTIN Pierre\n"
            "#Membre_1900 1900\nwit f: MARTIN Marie\n"
        )
        assert [e.event_type_raw for e in events] == ["Cours_peinture", "Membre_1900"]
        assert [w["person_id"] for w in events[0].witnesses] == ["MARTIN_Pierre_0"]
        assert [w["person_id"] for w in events[1].witnesses] == ["MARTIN_Marie_0"]

    def test_standard_tag_is_case_insensitive(self):
        events, _ = _pevt_events("#EDUC 1985\n")
        assert events[0].event_type == EventType.EDUCATION
        assert events[0].event_type_raw is None


class TestNoStandardTagIsLost:
    """Défaut 2 : tout événement présent dans le ``.gw`` est instancié."""

    @pytest.mark.parametrize("tag", STANDARD_TAGS)
    def test_each_standard_tag_yields_one_typed_event(self, tag):
        events, _ = _pevt_events(f"#{tag} 1990 #p Lille\n")
        assert len(events) == 1, f"#{tag} perdu"
        assert events[0].event_type == EventType(tag)
        assert events[0].event_type_raw is None
        assert events[0].place == "Lille"

    @pytest.mark.parametrize("tag", ["occu", "buri", "crem"])
    def test_formerly_lost_tags_without_date(self, tag):
        events, _ = _pevt_events(f"#{tag}\n")
        assert [e.event_type for e in events] == [EventType(tag)]

    def test_mix_of_all_kinds_keeps_every_event(self):
        events, _ = _pevt_events(
            "#birt 1900\n#occu 1920 #p Lille\n#Cours_peinture 1930\n"
            "#buri 1980\n#crem 1981\n#deat 1979\n"
        )
        assert len(events) == 6

    def test_gedcom_alias_bapm_is_baptism_and_keeps_raw_tag(self):
        events, _ = _pevt_events("#bapm 1993\n")
        assert events[0].event_type == EventType.BAPTISM
        assert events[0].event_type_raw == "bapm"

    def test_occu_event_does_not_hide_following_events(self):
        events, _ = _pevt_events("#occu 1995\n#educ 1985\n")
        assert [e.event_type for e in events] == [
            EventType.OCCUPATION,
            EventType.EDUCATION,
        ]


class TestNotesAttachedToEvents:
    """Défaut 3 : une ``note`` est rattachée à l'événement qui la précède."""

    def test_pevt_note_goes_to_preceding_event(self):
        events, person = _pevt_events("#cours 1990\nnote Une note\n")
        assert events[0].notes == ["Une note"]
        assert person.notes == []

    def test_each_event_gets_its_own_notes(self):
        events, _ = _pevt_events(
            "#cours 1990\nnote N1\nnote N1bis\n#occu 1995\nnote N2\n#Cours_x 1999\n"
        )
        assert events[0].notes == ["N1", "N1bis"]
        assert events[1].notes == ["N2"]
        assert events[2].notes == []

    def test_note_after_witness_still_belongs_to_event(self):
        events, _ = _pevt_events("#educ 1985\nwit m: MARTIN Pierre\nnote Diplôme\n")
        assert events[0].notes == ["Diplôme"]
        assert len(events[0].witnesses) == 1

    def test_note_with_punctuation_is_kept_verbatim(self):
        events, _ = _pevt_events(
            "#cours 1990\nnote Cours du soir, à Lyon (2 h/semaine).\n"
        )
        assert events[0].notes == ["Cours du soir, à Lyon (2 h/semaine)."]

    def test_fevt_notes_attach_to_their_event(self):
        genealogy = GeneWebParser().parse_string(
            HEADER
            + "fam DUPONT Jean + MARTIN Marie\n"
            + "fevt\n#marr 1900 #p Paris\nnote Note mariage\n"
            + "#div 1910\nnote Note divorce\nend fevt\n"
        )
        family = next(iter(genealogy.families.values()))
        notes = [e.notes for e in family.events]
        assert notes == [["Note mariage"], ["Note divorce"]]


class TestStructuredPlace:
    """Défaut 4 : ``[complément]_-_lieu`` décomposé, chaîne brute préservée."""

    def test_bracketed_complement(self):
        parsed = parse_place("[Atelier Rose] - Lyon")
        assert parsed == ParsedPlace(
            raw="[Atelier Rose] - Lyon", complement="Atelier Rose", name="Lyon"
        )

    def test_plain_place(self):
        parsed = parse_place("Paris")
        assert (parsed.complement, parsed.name, parsed.raw) == (None, "Paris", "Paris")

    def test_hyphenated_toponyms_are_not_altered(self):
        for nom in ("Saint-Maur-des-Fossés", "Saint-Denis (93)", "Aix-en-Provence"):
            parsed = parse_place(nom)
            assert (parsed.name, parsed.complement) == (nom, None)

    def test_literal_underscore_is_kept(self):
        assert parse_place("Lieu_dit").name == "Lieu_dit"

    def test_complement_without_brackets(self):
        parsed = parse_place("Ecole primaire - Lyon")
        assert (parsed.complement, parsed.name) == ("Ecole primaire", "Lyon")

    def test_empty_or_none(self):
        assert parse_place(None) is None
        assert parse_place("   ") is None

    def test_event_exposes_parts_and_keeps_raw_place(self):
        events, _ = _pevt_events("#Cours_peinture 1990 #p [Atelier_Rose]_-_Lyon\n")
        assert events[0].place == "[Atelier Rose] - Lyon"
        assert events[0].place_parts.complement == "Atelier Rose"
        assert events[0].place_parts.name == "Lyon"

    def test_event_without_place_has_no_parts(self):
        events, _ = _pevt_events("#Cours_peinture 1990\n")
        assert events[0].place_parts is None
