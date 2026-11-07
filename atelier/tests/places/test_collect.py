from pathlib import Path

import pytest
from geneweb_py import GeneWebParser
from geneweb_py.formats.tables import Table, build_base_tables

from prosopo_gw_atelier.places.collect import collect_writings
from prosopo_gw_atelier.places.model import Occurrence, Writing

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lieux_varies.gw"


@pytest.fixture(scope="module")
def tables() -> list[Table]:
    return build_base_tables(GeneWebParser().parse_file(str(FIXTURE)))


@pytest.fixture(scope="module")
def writings(tables: list[Table]) -> dict[str, Writing]:
    return collect_writings(tables)


def test_complement_is_removed_from_the_key(writings: dict[str, Writing]) -> None:
    lyon = writings["Lyon"]
    assert lyon.text == "Lyon"
    assert len(lyon.occurrences) == 2
    assert [o.complement for o in lyon.occurrences] == [None, "Atelier Rose"]
    assert "[Atelier Rose] - Lyon" not in writings


def test_occurrence_of_an_event(writings: dict[str, Writing]) -> None:
    occurrence = writings["Lyon"].occurrences[1]
    assert occurrence == Occurrence(
        table="evenements",
        row_id="pevt:DUPONT_Jean_0:2",
        column="lieu",
        complement="Atelier Rose",
        event_type="occu",
        date="1872",
    )


def test_birth_in_personnes_and_in_evenements_counts_once(
    writings: dict[str, Writing],
) -> None:
    """The ``#birt`` event repeats the person's birth: one occurrence, the column."""
    occurrences = writings["St-Omer (62)"].occurrences
    assert occurrences == [
        Occurrence(
            "personnes", "DUPONT_Anne_0", "naissance_lieu", None, "naissance", "1878"
        ),
    ]


def _person(pid: str, **values: str | None) -> dict[str, str | None]:
    from geneweb_py.formats.tables import PERSONNES

    row: dict[str, str | None] = dict.fromkeys(PERSONNES.column_names)
    row.update(personne_id=pid, **values)
    return row


def _family(fid: str, **values: str | None) -> dict[str, str | None]:
    from geneweb_py.formats.tables import FAMILLES

    row: dict[str, str | None] = dict.fromkeys(FAMILLES.column_names)
    row.update(famille_id=fid, **values)
    return row


def _event(eid: str, **values: str | None) -> dict[str, str | None]:
    from geneweb_py.formats.tables import EVENEMENTS

    row: dict[str, str | None] = dict.fromkeys(EVENEMENTS.column_names)
    row.update(evenement_id=eid, **values)
    return row


def _collect(
    persons: list[dict[str, str | None]],
    families: list[dict[str, str | None]],
    events: list[dict[str, str | None]],
) -> dict[str, Writing]:
    from geneweb_py.formats.tables import EVENEMENTS, FAMILLES, PERSONNES

    return collect_writings(
        [
            Table(PERSONNES, list(persons)),
            Table(FAMILLES, list(families)),
            Table(EVENEMENTS, list(events)),
        ]
    )


def test_event_repeating_a_column_counts_once() -> None:
    writings = _collect(
        [_person("P1", deces_lieu="Arras", deces_date="1910")],
        [_family("F1", mariage_lieu="Lille", mariage_date="1875")],
        [
            _event("E1", personne_id="P1", type="deat", lieu="Arras", date="1910"),
            _event("E2", famille_id="F1", type="marr", lieu="Lille", date="1875"),
        ],
    )
    assert [(o.table, o.column) for o in writings["Arras"].occurrences] == [
        ("personnes", "deces_lieu")
    ]
    assert [(o.table, o.column) for o in writings["Lille"].occurrences] == [
        ("familles", "mariage_lieu")
    ]


def test_dated_event_replaces_an_undated_column() -> None:
    writings = _collect(
        [_person("P1", naissance_lieu="Arras")],
        [],
        [_event("E1", personne_id="P1", type="birt", lieu="Arras", date="1850")],
    )
    assert writings["Arras"].occurrences == [
        Occurrence("evenements", "E1", "lieu", None, "birt", "1850")
    ]


def test_events_that_are_not_the_column_still_count() -> None:
    writings = _collect(
        [_person("P1", naissance_lieu="Arras", deces_lieu="Lille")],
        [],
        [
            # another person, another kind, another place, another complement
            _event("E1", personne_id="P2", type="birt", lieu="Arras"),
            _event("E2", personne_id="P1", type="bapt", lieu="Arras"),
            _event("E3", personne_id="P1", type="deat", lieu="Lyon"),
            _event("E4", personne_id="P1", type="deat", lieu="[Hospice] - Lille"),
        ],
    )
    assert len(writings["Arras"].occurrences) == 3
    assert len(writings["Lille"].occurrences) == 2
    assert len(writings["Lyon"].occurrences) == 1


def test_a_column_absorbs_one_event_only() -> None:
    writings = _collect(
        [_person("P1", naissance_lieu="Arras")],
        [],
        [
            _event("E1", personne_id="P1", type="birt", lieu="Arras"),
            _event("E2", personne_id="P1", type="birt", lieu="Arras"),
        ],
    )
    assert [o.table for o in writings["Arras"].occurrences] == [
        "personnes",
        "evenements",
    ]


def test_death_and_marriage_columns(writings: dict[str, Writing]) -> None:
    death = writings["59100 Roubaix"].occurrences[0]
    assert (death.table, death.row_id, death.column) == (
        "personnes",
        "MARTIN_Marie_0",
        "deces_lieu",
    )
    assert (death.event_type, death.date) == ("deces", "1920")
    marriage = writings["Lille, Nord, France"].occurrences[0]
    assert (marriage.table, marriage.row_id, marriage.column) == (
        "familles",
        "FAM_002",
        "mariage_lieu",
    )
    assert (marriage.event_type, marriage.date) == ("mariage", "1880")


def test_case_variants_stay_distinct(writings: dict[str, Writing]) -> None:
    assert "ROUBAIX, Nord, France" in writings
    assert "roubaix, Nord-Pas-de-Calais" in writings
    assert "Roubaix" in writings


def test_order_of_first_appearance(writings: dict[str, Writing]) -> None:
    keys = list(writings)
    assert keys[0] == "Lille"
    assert keys == list(dict.fromkeys(keys))
    assert all(w.text == key for key, w in writings.items())


def test_blank_cells_are_skipped() -> None:
    from geneweb_py.formats.tables import EVENEMENTS, PERSONNES

    person = dict.fromkeys(PERSONNES.column_names)
    person.update(personne_id="P1", naissance_lieu="  ", deces_lieu="")
    event = dict.fromkeys(EVENEMENTS.column_names)
    event.update(evenement_id="E1", lieu=None)
    tables = [Table(PERSONNES, [person]), Table(EVENEMENTS, [event])]
    assert collect_writings(tables) == {}


def test_deterministic(tables: list[Table]) -> None:
    assert collect_writings(tables) == collect_writings(tables)
