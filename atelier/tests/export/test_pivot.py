import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from geneweb_py import GeneWebParser
from geneweb_py.formats.table_writers import dictionary_table
from geneweb_py.formats.tables import Row, Table, build_base_tables

from prosopo_gw_atelier.export.pivot import (
    ECRITURES_LIEUX,
    LIEUX,
    NIVEAUX_LIEUX,
    build_pivot,
)
from prosopo_gw_atelier.places.levels import Level, LevelOrigin
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


def commune(name: str) -> list[Level]:
    return [Level(0, name, type="commune", origin="rule")]


def add(
    registry: PlaceRegistry,
    writings: list[str],
    levels: list[Level],
    project: str = "p",
    postal: tuple[str, LevelOrigin] | None = None,
) -> str:
    code, origin = postal if postal else (None, None)
    return registry.validate(writings, levels, code, origin, project=project).place_id


@pytest.fixture
def lyon(registry: PlaceRegistry) -> str:
    return add(
        registry,
        ["Lyon"],
        [
            Level(0, "Lyon", type="commune", identifier="69123", origin="rule"),
            Level(1, "Rhône", type="departement", origin="manual"),
        ],
    )


@pytest.fixture
def marconne(registry: PlaceRegistry) -> str:
    # "Lille" is a writing of lieux_varies.gw: the place is exported
    return add(
        registry,
        ["Lille"],
        [
            Level(
                0,
                "Marconne",
                type="commune_historique",
                identifier="62549",
                source="COG 2026",
                end="2025-01-01",
                nature="deleguee",
                origin="insee",
            ),
            Level(
                1, "Hesdin-la-Forêt", type="commune", identifier="62447", origin="insee"
            ),
            Level(2, "Pas-de-Calais", type="departement", identifier="62"),
            Level(3, "Hauts-de-France", type="region", origin="insee"),
            Level(4, "France", type="pays", origin="written"),
        ],
        postal=("62140", "insee"),
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
    assert names == [t.spec.name for t in core_tables] + [
        "lieux",
        "niveaux_lieux",
        "ecritures_lieux",
    ]


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
    arras = add(registry, ["Arras"], commune("Arras"))
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
    roubaix = add(registry, ["Roubaix"], commune("Roubaix"))
    families = by_name(build_pivot(core_tables, registry))["familles"]
    assert row(families, "FAM_001")["mariage_lieu_id"] == roubaix
    assert row(families, "FAM_001")["mariage_complement"] is None
    assert row(families, "FAM_002")["mariage_lieu_id"] is None


LIEUX_COLUMNS = [
    "lieu_id",
    "commune",
    "code_insee",
    "code_postal",
    "departement",
    "region",
    "pays",
    "commune_historique",
    "code_insee_historique",
    "libelle",
    "latitude",
    "longitude",
]
ORIGIN_COLUMNS = [
    f"{c}_origine"
    for c in [
        "commune",
        "code_insee",
        "code_postal",
        "departement",
        "region",
        "pays",
        "commune_historique",
        "code_insee_historique",
    ]
]


def test_places_table_lists_only_places_of_this_gw(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    add(registry, ["Paris"], commune("Paris"), project="other")
    roubaix = add(
        registry,
        ["Roubaix", "ROUBAIX, Nord, France"],
        [
            Level(0, "Roubaix", type="commune", identifier="59512", origin="rule"),
            Level(1, "Hauts-de-France", type="region", origin="insee"),
            Level(2, "France", type="pays", origin="manual"),
        ],
        postal=("59100", "rule"),
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
        "commune_historique": None,
        "code_insee_historique": None,
        "libelle": "Lyon, Rhône",
        "latitude": None,
        "longitude": None,
        "commune_origine": "regle",
        "code_insee_origine": "regle",
        "code_postal_origine": None,
        "departement_origine": "manuel",
        "region_origine": None,
        "pays_origine": None,
        "commune_historique_origine": None,
        "code_insee_historique_origine": None,
    }
    roubaix_row = next(r for r in places.rows if r["lieu_id"] == roubaix)
    assert roubaix_row["code_postal"] == "59100"
    assert roubaix_row["code_postal_origine"] == "regle"
    assert roubaix_row["pays"] == "France"
    assert roubaix_row["pays_origine"] == "manuel"
    assert roubaix_row["region_origine"] == "insee"


def test_places_spec_columns() -> None:
    assert LIEUX.column_names == LIEUX_COLUMNS + ORIGIN_COLUMNS
    assert LIEUX.primary_key == "lieu_id"
    assert ECRITURES_LIEUX.column_names == ["ecriture", "lieu_id", "statut"]
    assert "ancien_nom" not in LIEUX.column_names


def test_lieux_columns() -> None:
    assert LIEUX.column_names == [
        "lieu_id",
        "commune",
        "code_insee",
        "code_postal",
        "departement",
        "region",
        "pays",
        "commune_historique",
        "code_insee_historique",
        "libelle",
        "latitude",
        "longitude",
        "commune_origine",
        "code_insee_origine",
        "code_postal_origine",
        "departement_origine",
        "region_origine",
        "pays_origine",
        "commune_historique_origine",
        "code_insee_historique_origine",
    ]
    assert NIVEAUX_LIEUX.column_names == [
        "lieu_id",
        "rang",
        "nom",
        "nom_ecrit",
        "type",
        "nature",
        "identifiant",
        "source",
        "debut",
        "fin",
        "latitude",
        "longitude",
        "origine",
    ]


def test_niveaux_lieux_rows(
    core_tables: list[Table], registry: PlaceRegistry, marconne: str
) -> None:
    levels = by_name(build_pivot(core_tables, registry))["niveaux_lieux"]
    assert levels.spec is NIVEAUX_LIEUX
    assert [r["rang"] for r in levels.rows] == [0, 1, 2, 3, 4]
    assert {r["lieu_id"] for r in levels.rows} == {marconne}
    first = levels.rows[0]
    assert first["nom"] == "Marconne"
    assert first["type"] == "commune_historique"
    assert first["identifiant"] == "62549"
    assert first["nature"] == "deleguee"
    assert first["fin"] == "2025-01-01"
    assert first["origine"] == "insee"
    assert first["source"] == "COG 2026"
    assert levels.rows[4]["origine"] == "ecrit"


def test_lieux_row_of_a_historical_commune(
    core_tables: list[Table], registry: PlaceRegistry, marconne: str
) -> None:
    lieu = by_name(build_pivot(core_tables, registry))["lieux"].rows[0]
    assert lieu["commune"] == "Hesdin-la-Forêt"
    assert lieu["code_insee"] == "62447"
    assert lieu["commune_historique"] == "Marconne"
    assert lieu["code_insee_historique"] == "62549"
    assert lieu["commune_historique_origine"] == "insee"
    assert lieu["code_postal"] == "62140"
    assert lieu["code_postal_origine"] == "insee"


def test_proposed_levels_not_exported(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    place = add(
        registry,
        ["Lille"],
        [
            Level(
                0,
                "Marconne",
                type="commune_historique",
                identifier="62549",
                nature="deleguee",
                origin="insee",
                status="proposed",
            ),
            Level(1, "Hesdin-la-Forêt", type="commune", identifier="62447"),
            Level(2, "France", type="pays", origin="written"),
        ],
    )
    pivot = by_name(build_pivot(core_tables, registry))
    levels = pivot["niveaux_lieux"].rows
    assert [(r["rang"], r["nom"]) for r in levels] == [
        (0, "Hesdin-la-Forêt"),
        (1, "France"),
    ]
    lieu = pivot["lieux"].rows[0]
    assert lieu["lieu_id"] == place
    assert lieu["commune_historique"] is None
    assert lieu["libelle"] == "Hesdin-la-Forêt, France"


def test_libelle(
    core_tables: list[Table], registry: PlaceRegistry, marconne: str
) -> None:
    lieu = by_name(build_pivot(core_tables, registry))["lieux"].rows[0]
    assert (
        lieu["libelle"]
        == "Marconne, Hesdin-la-Forêt, Pas-de-Calais, Hauts-de-France, France"
    )


def test_coordinates_come_from_the_most_precise_located_level(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    add(
        registry,
        ["Lille"],
        [
            Level(0, "Lille", type="commune"),
            Level(1, "Nord", type="departement", latitude=50.5, longitude=3.2),
        ],
    )
    lieu = by_name(build_pivot(core_tables, registry))["lieux"].rows[0]
    assert (lieu["latitude"], lieu["longitude"]) == (50.5, 3.2)


def test_place_without_validated_level_does_not_crash(
    core_tables: list[Table], registry: PlaceRegistry
) -> None:
    place = add(
        registry,
        ["Lyon"],
        [Level(0, "Lyon", type="commune", identifier="69123", status="proposed")],
    )
    pivot = by_name(build_pivot(core_tables, registry))
    assert pivot["lieux"].rows == [
        {
            **{c: None for c in LIEUX.column_names},
            "lieu_id": place,
        }
    ]
    assert pivot["niveaux_lieux"].rows == []


def test_niveaux_lieux_only_for_places_of_this_gw(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    add(registry, ["Paris"], commune("Paris"), project="other")
    levels = by_name(build_pivot(core_tables, registry))["niveaux_lieux"]
    assert {r["lieu_id"] for r in levels.rows} == {lyon}


def test_writings_table(
    core_tables: list[Table], registry: PlaceRegistry, lyon: str
) -> None:
    registry.reject(["En mer"], project="p")
    registry.reject(["Ailleurs"], project="other")  # not in this .gw
    add(registry, ["Paris"], commune("Paris"), project="other")
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
    assert pivot["niveaux_lieux"].rows == []
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
    for column in NIVEAUX_LIEUX.column_names:
        assert entries[("niveaux_lieux", column)]
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
    def places() -> list[Place]:
        level = Level(0, "Lyon", type="commune", origin="guess")  # type: ignore[arg-type]
        return [Place(lyon, (level,))]

    monkeypatch.setattr(registry, "places", places)
    with pytest.raises(ValueError, match="guess"):
        build_pivot(core_tables, registry)
