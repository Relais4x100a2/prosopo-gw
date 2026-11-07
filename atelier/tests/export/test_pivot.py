import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from geneweb_py import GeneWebParser
from geneweb_py.formats.table_writers import dictionary_table
from geneweb_py.formats.tables import Row, Table, build_base_tables

from prosopo_gw_atelier.export.pivot import ECRITURES_LIEUX, LIEUX, build_pivot
from prosopo_gw_atelier.store.registry import Decision, Place, PlaceRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

ADDED = {
    "personnes": [
        "naissance_lieu_id",
        "naissance_complement",
        "deces_lieu_id",
        "deces_complement",
    ],
    "familles": ["mariage_lieu_id", "mariage_complement"],
    "evenements": ["lieu_id"],
}
FOLLOWS = {
    "naissance_lieu_id": "naissance_lieu",
    "naissance_complement": "naissance_lieu_id",
    "deces_lieu_id": "deces_lieu",
    "deces_complement": "deces_lieu_id",
    "mariage_lieu_id": "mariage_lieu",
    "mariage_complement": "mariage_lieu_id",
    "lieu_id": "lieu",
}


@pytest.fixture(scope="module")
def core_tables() -> list[Table]:
    parser = GeneWebParser()
    return build_base_tables(parser.parse_file(str(FIXTURES / "lieux_varies.gw")))


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "referentiel.sqlite") as reg:
        yield reg


@pytest.fixture
def lyon(registry: PlaceRegistry) -> str:
    return registry.validate(
        ["Lyon"],
        {"commune": "Lyon", "insee_code": "69123", "department": "Rhône"},
        {"commune": "rule", "insee_code": "rule", "department": "manual"},
        project="p",
    )


def by_name(tables: list[Table]) -> dict[str, Table]:
    return {t.spec.name: t for t in tables}


def row(table: Table, key: str) -> Row:
    pk = table.spec.primary_key
    assert pk is not None
    return next(r for r in table.rows if r[pk] == key)


def test_core_columns_keep_names_and_order(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    pivot = by_name(build_pivot(core_tables, registry))
    for original in core_tables:
        name = original.spec.name
        added = ADDED.get(name, [])
        kept = [c for c in pivot[name].spec.column_names if c not in added]
        assert kept == original.spec.column_names
        assert set(pivot[name].spec.column_names) - set(kept) == set(added)
        assert pivot[name].spec.primary_key == original.spec.primary_key


def test_added_columns_follow_their_place_column(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    pivot = by_name(build_pivot(core_tables, registry))
    for name, added in ADDED.items():
        columns = pivot[name].spec.column_names
        for column in added:
            assert columns.index(column) == columns.index(FOLLOWS[column]) + 1


def test_tables_in_core_order_then_places(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    names = [t.spec.name for t in build_pivot(core_tables, registry)]
    assert names == [t.spec.name for t in core_tables] + ["lieux", "ecritures_lieux"]


def test_original_values_untouched(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    before = copy.deepcopy(core_tables)
    pivot = by_name(build_pivot(core_tables, registry))
    assert core_tables == before  # inputs not mutated
    for original in core_tables:
        rows = pivot[original.spec.name].rows
        assert len(rows) == len(original.rows)
        for new, old in zip(rows, original.rows, strict=True):
            assert {k: new[k] for k in old} == old


def test_validated_writing_gets_its_place_id(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    events = by_name(build_pivot(core_tables, registry))["evenements"]
    resi = row(events, "pevt:DUPONT_Jean_0:1")
    assert resi["lieu"] == "Lyon"
    assert resi["lieu_id"] == lyon
    assert resi["complement"] is None


def test_complement_is_kept_apart_from_the_place(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    events = by_name(build_pivot(core_tables, registry))["evenements"]
    occu = row(events, "pevt:DUPONT_Jean_0:2")
    assert occu["lieu"] == "[Atelier Rose] - Lyon"
    assert occu["lieu_id"] == lyon
    assert occu["complement"] == "Atelier Rose"


def test_person_columns(core_tables: list[Table], registry: PlaceRegistry) -> None:
    arras = registry.validate(
        ["Arras"], {"commune": "Arras"}, {"commune": "rule"}, project="p"
    )
    registry.reject(["En mer"], project="p")
    persons = by_name(build_pivot(core_tables, registry))["personnes"]
    louise = row(persons, "PETIT_Louise_0")
    assert louise["naissance_lieu"] == "[Rue des Fleurs] - Arras"
    assert louise["naissance_lieu_id"] == arras
    assert louise["naissance_complement"] == "Rue des Fleurs"
    # rejected: no place id, original writing kept
    assert louise["deces_lieu"] == "En mer"
    assert louise["deces_lieu_id"] is None
    assert louise["deces_complement"] is None
    # undecided
    jean = row(persons, "DUPONT_Jean_0")
    assert jean["naissance_lieu"] == "Lille"
    assert jean["naissance_lieu_id"] is None
    # empty place cell
    anne = row(persons, "DUPONT_Anne_0")
    assert anne["deces_lieu_id"] is None
    assert anne["deces_complement"] is None


def test_family_columns(core_tables: list[Table], registry: PlaceRegistry) -> None:
    roubaix = registry.validate(
        ["Roubaix"], {"commune": "Roubaix"}, {"commune": "rule"}, project="p"
    )
    families = by_name(build_pivot(core_tables, registry))["familles"]
    assert row(families, "FAM_001")["mariage_lieu_id"] == roubaix
    assert row(families, "FAM_001")["mariage_complement"] is None
    assert row(families, "FAM_002")["mariage_lieu_id"] is None


def test_places_table_lists_only_places_of_this_gw(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    registry.validate(
        ["Paris"], {"commune": "Paris"}, {"commune": "rule"}, project="other"
    )
    roubaix = registry.validate(
        ["Roubaix", "ROUBAIX, Nord, France"],
        {
            "commune": "Roubaix",
            "postal_code": "59100",
            "country": "France",
            "region": "Hauts-de-France",
            "former_name": "Roubaix-Ancien",
        },
        {
            "commune": "rule",
            "postal_code": "rule",
            "country": "manual",
            "region": "reference",
            "former_name": "llm",
        },
        project="p",
    )
    places = by_name(build_pivot(core_tables, registry))["lieux"]
    assert places.spec is LIEUX
    assert [r["lieu_id"] for r in places.rows] == sorted([lyon, roubaix])
    lyon_row = next(r for r in places.rows if r["lieu_id"] == lyon)
    assert lyon_row == {
        "lieu_id": lyon,
        "commune": "Lyon",
        "code_insee": "69123",
        "code_postal": None,
        "departement": "Rhône",
        "region": None,
        "pays": None,
        "ancien_nom": None,
        "commune_origine": "regle",
        "code_insee_origine": "regle",
        "code_postal_origine": None,
        "departement_origine": "manuel",
        "region_origine": None,
        "pays_origine": None,
        "ancien_nom_origine": None,
    }
    roubaix_row = next(r for r in places.rows if r["lieu_id"] == roubaix)
    assert roubaix_row["code_postal"] == "59100"
    assert roubaix_row["pays"] == "France"
    assert roubaix_row["pays_origine"] == "manuel"
    assert roubaix_row["region_origine"] == "referentiel"
    assert roubaix_row["ancien_nom"] == "Roubaix-Ancien"
    assert roubaix_row["ancien_nom_origine"] == "llm"


def test_places_spec_columns() -> None:
    values = [
        "commune",
        "code_insee",
        "code_postal",
        "departement",
        "region",
        "pays",
        "ancien_nom",
    ]
    assert LIEUX.column_names == ["lieu_id", *values] + [f"{v}_origine" for v in values]
    assert LIEUX.primary_key == "lieu_id"
    assert ECRITURES_LIEUX.column_names == ["ecriture", "lieu_id", "statut"]


def test_writings_table(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    registry.reject(["En mer"], project="p")
    registry.reject(["Ailleurs"], project="other")  # not in this .gw
    registry.validate(["Paris"], {"commune": "Paris"}, {"commune": "rule"}, "other")
    writings = by_name(build_pivot(core_tables, registry))["ecritures_lieux"]
    assert writings.spec is ECRITURES_LIEUX
    assert writings.rows == [
        {"ecriture": "En mer", "lieu_id": None, "statut": "rejete"},
        {"ecriture": "Lyon", "lieu_id": lyon, "statut": "valide"},
    ]


def test_no_decision_gives_empty_places_tables(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    pivot = by_name(build_pivot(core_tables, registry))
    assert pivot["lieux"].rows == []
    assert pivot["ecritures_lieux"].rows == []
    assert all(r["lieu_id"] is None for r in pivot["evenements"].rows)


def test_dictionary_describes_the_new_columns(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    pivot = build_pivot(core_tables, registry)
    entries = {
        (r["table"], r["colonne"]): r["description"]
        for r in dictionary_table([t.spec for t in pivot]).rows
    }
    for name, added in ADDED.items():
        for column in added:
            assert entries[(name, column)]
    for column in LIEUX.column_names:
        assert entries[("lieux", column)]
    for column in ECRITURES_LIEUX.column_names:
        assert entries[("ecritures_lieux", column)]


def test_unknown_stored_status_raises(
    core_tables: list[Table], registry: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def decisions(writings: Any) -> dict[str, Decision]:
        return {"Lyon": Decision("Lyon", None, "pending", "p")}  # type: ignore[arg-type]

    monkeypatch.setattr(registry, "decisions", decisions)
    with pytest.raises(ValueError, match="pending"):
        build_pivot(core_tables, registry)


def test_unknown_stored_origin_raises(
    core_tables: list[Table],
    registry: PlaceRegistry,
    lyon: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def place(place_id: str) -> Place:
        return Place(place_id, {"commune": "Lyon"}, {"commune": "guess"})  # type: ignore[dict-item]

    monkeypatch.setattr(registry, "place", place)
    with pytest.raises(ValueError, match="guess"):
        build_pivot(core_tables, registry)
