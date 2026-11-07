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


def test_birth_counts_in_personnes_and_in_evenements(
    writings: dict[str, Writing],
) -> None:
    occurrences = writings["St-Omer (62)"].occurrences
    assert occurrences == [
        Occurrence(
            "personnes", "DUPONT_Anne_0", "naissance_lieu", None, "naissance", "1878"
        ),
        Occurrence("evenements", "pevt:DUPONT_Anne_0:0", "lieu", None, "birt", "1878"),
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
