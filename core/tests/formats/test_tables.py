"""Tables de l'export : personnes, familles, enfants, événements, témoins.

Fixtures 100 % synthétiques.
"""

from pathlib import Path

import pytest

from geneweb_py.core.event_to_organization import event_ref
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.formats.tables import (
    EVENT_TYPE_LABELS,
    Table,
    build_base_tables,
    family_event_ref,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rich_pevt_wit.gw"


def _parse() -> Genealogy:
    return GeneWebParser().parse_file(str(FIXTURE))


def _tables(genealogy: Genealogy) -> dict[str, Table]:
    return {t.spec.name: t for t in build_base_tables(genealogy)}


@pytest.fixture
def tables() -> dict[str, Table]:
    return _tables(_parse())


def _rows(tables: dict[str, Table], name: str, **where: object) -> list[dict]:
    return [r for r in tables[name].rows if all(r[k] == v for k, v in where.items())]


def test_table_order_and_columns() -> None:
    built = build_base_tables(_parse())
    assert [t.spec.name for t in built] == [
        "personnes",
        "familles",
        "enfants",
        "evenements",
        "temoins",
        "sources",
    ]
    for table in built:
        for row in table.rows:
            assert list(row) == table.spec.column_names


def test_person_row(tables: dict[str, Table]) -> None:
    (row,) = _rows(tables, "personnes", personne_id="DUPONT_Jean_0")
    assert row["nom"] == "DUPONT"
    assert row["prenom"] == "Jean"
    assert row["occurrence"] == 0
    assert row["sexe"] == "M"
    assert row["naissance_date"] == "1870"
    assert row["naissance_annee"] == 1870
    assert row["naissance_lieu"] == "Lyon"
    assert row["deces_annee"] == 1925
    assert row["note"] is None


def test_children_rank(tables: dict[str, Table]) -> None:
    (row,) = tables["enfants"].rows
    assert row == {"famille_id": "FAM_001", "personne_id": "Louis_DUPONT_0", "rang": 1}


def test_event_ids_and_labels(tables: dict[str, Table]) -> None:
    row = tables["evenements"].rows[0]
    assert row["evenement_id"] == event_ref("DUPONT_Jean_0", 0)
    assert row["personne_id"] == "DUPONT_Jean_0"
    assert row["famille_id"] is None
    assert row["type"] == "birt"
    assert row["type_libelle"] == EVENT_TYPE_LABELS["birt"] == "Naissance"
    assert row["annee"] == 1870
    assert row["ville"] == "Lyon"


def test_free_event_label(tables: dict[str, Table]) -> None:
    (row,) = _rows(tables, "evenements", evenement_id=event_ref("DUPONT_Jean_0", 2))
    assert row["type"] == "oth"
    assert row["type_libelle"] == "Autre"
    assert row["libelle"] == "Cours peinture"


def test_event_note(tables: dict[str, Table]) -> None:
    (row,) = _rows(tables, "evenements", evenement_id=event_ref("DUPONT_Jean_0", 1))
    assert row["note"] == "Apprenti"
    assert row["complement"] == "Atelier Rose"


def test_family_event(tables: dict[str, Table]) -> None:
    (row,) = _rows(tables, "evenements", evenement_id=family_event_ref("FAM_001", 0))
    assert family_event_ref("FAM_001", 0) == "fevt:FAM_001:0"
    assert row["personne_id"] is None
    assert row["famille_id"] == "FAM_001"
    assert row["type"] == "marr"
    assert row["type_libelle"] == "Mariage"
    assert row["ville"] == "Lyon"
    assert row["complement"] == "Mairie"
    assert row["note"] == "Note de mariage"


def test_witness_rows(tables: dict[str, Table]) -> None:
    family = _rows(tables, "temoins", famille_id="FAM_001")
    assert family and all(r["evenement_id"] is None for r in family)
    occu = _rows(tables, "temoins", evenement_id=event_ref("DUPONT_Jean_0", 1))
    assert occu == [
        {
            "evenement_id": event_ref("DUPONT_Jean_0", 1),
            "famille_id": None,
            "personne_id": "MARTIN_Pierre_0",
            "role": "Témoin",
        }
    ]
    marr = _rows(tables, "temoins", evenement_id=family_event_ref("FAM_001", 0))
    assert [r["personne_id"] for r in marr] == ["DURAND_Paul_0"]


def test_godparent_role() -> None:
    text = (
        "encoding: utf-8\ngwplus\n\n"
        "pevt DUPONT Jean\n#bapt 1870\nwit m: #godp MARTIN Pierre\nend pevt\n"
    )
    tables = _tables(GeneWebParser().parse_string(text))
    roles = [r["role"] for r in tables["temoins"].rows]
    assert roles == ["Parrain ou marraine"]


def test_missing_values_are_none() -> None:
    tables = _tables(
        GeneWebParser().parse_string("encoding: utf-8\n\nfam ? ? + DUPONT Anne\n")
    )
    (family,) = tables["familles"].rows
    assert family["mariage_date"] is None
    assert family["mariage_annee"] is None
    assert family["mariage_lieu"] is None
    assert family["note"] is None
    (anne,) = _rows(tables, "personnes", personne_id="DUPONT_Anne_0")
    assert anne["naissance_date"] is None and anne["naissance_annee"] is None
    assert anne["sexe"] == "F"


def test_references_resolve(tables: dict[str, Table]) -> None:
    persons = {r["personne_id"] for r in tables["personnes"].rows}
    families = {r["famille_id"] for r in tables["familles"].rows}
    events = {r["evenement_id"] for r in tables["evenements"].rows}
    for f in tables["familles"].rows:
        assert {f["mari_id"], f["femme_id"]} - {None} <= persons
    for name in ("enfants", "evenements", "temoins"):
        for r in tables[name].rows:
            assert r.get("personne_id") in persons | {None}
            assert r.get("famille_id") in families | {None}
    for r in tables["temoins"].rows:
        assert r["evenement_id"] in events | {None}


def test_ids_stable() -> None:
    first = [t.rows for t in build_base_tables(_parse())]
    second = [t.rows for t in build_base_tables(_parse())]
    assert first == second
