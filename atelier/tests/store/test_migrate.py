"""Migration of a version 1 registry (fixed fields) to level chains."""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from prosopo_gw_atelier.places.levels import Level
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store import migrate
from prosopo_gw_atelier.store.migrate import backup_path, levels_from_v1
from prosopo_gw_atelier.store.registry import PlaceRegistry, SchemaVersionError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MINI = FIXTURES / "refdata_mini"
AT = "'2026-11-01T00:00:00+00:00'"


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(MINI)


def _v1_registry(path: Path, extra: str = "") -> None:
    """Base v1 synthétique : Lille avec ancien nom Lomme (2 écritures), Winnipeg
    sans Manitoba, une écriture rejetée."""
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / "registry_v1.sql").read_text("utf-8"))
    conn.executescript(f"""
      INSERT INTO places VALUES ('p-lille', {AT}), ('p-winnipeg', {AT});
      INSERT INTO place_fields VALUES
        ('p-lille','commune','Lille','reference'),
        ('p-lille','insee_code','59350','reference'),
        ('p-lille','department','59','reference'),
        ('p-lille','region','Hauts-de-France','reference'),
        ('p-lille','country','France','rule'), ('p-lille','former_name','Lomme','rule'),
        ('p-lille','postal_code','59000','rule'),
        ('p-winnipeg','commune','Winnipeg','rule'),
        ('p-winnipeg','country','Canada','rule');
      INSERT INTO writings VALUES
        ('Lille', 'p-lille', 'validated', 'p1', {AT}),
        ('Lomme', 'p-lille', 'validated', 'p1', {AT}),
        ('Winnipeg, , , Manitoba, Canada', 'p-winnipeg', 'validated', 'p1', {AT}),
        ('en mer', NULL, 'rejected', 'p1', {AT});
      {extra}
    """)
    conn.close()


def test_decisions_survive(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        d = registry.decisions(
            ["Lille", "Lomme", "Winnipeg, , , Manitoba, Canada", "en mer"]
        )
        assert {w: (x.status, x.place_id) for w, x in d.items()} == {
            "Lille": ("validated", "p-lille"),
            "Lomme": ("validated", "p-lille"),
            "Winnipeg, , , Manitoba, Canada": ("validated", "p-winnipeg"),
            "en mer": ("rejected", None),
        }


def test_writing_rows_are_unchanged(tmp_path: Path, ref: RefData) -> None:
    path = tmp_path / "r.sqlite"
    _v1_registry(path)
    conn = sqlite3.connect(path)
    before = conn.execute("SELECT * FROM writings ORDER BY writing").fetchall()
    conn.close()
    PlaceRegistry(path, ref).close()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT * FROM writings ORDER BY writing").fetchall() == before
    conn.close()


def test_lille_levels_and_lomme_proposal(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        place = registry.place("p-lille")
    assert [(lv.name, lv.type, lv.status) for lv in place.levels] == [
        ("Lomme", "commune_historique", "proposed"),
        ("Lille", "commune", "validated"),
        ("Nord", "departement", "validated"),
        ("Hauts-de-France", "region", "validated"),
        ("France", "pays", "validated"),
    ]
    assert place.levels[0].identifier == "59355" and place.levels[1].origin == "insee"
    assert place.levels[0].nature == "associee"
    assert place.levels[0].end == "2000-02-27"
    assert place.levels[2].identifier == "59"
    assert place.levels[4].origin == "rule"
    assert place.postal_code == "59000" and place.postal_origin == "rule"


def test_winnipeg_gets_manitoba_as_proposal(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        place = registry.place("p-winnipeg")
    assert [(lv.name, lv.status) for lv in place.levels] == [
        ("Winnipeg", "validated"),
        ("Manitoba", "proposed"),
        ("Canada", "validated"),
    ]
    assert place.levels[1].origin == "written" and place.levels[1].type is None


def test_level_written_before_the_commune_is_proposed_before_it(
    tmp_path: Path, ref: RefData
) -> None:
    _v1_registry(
        tmp_path / "r.sqlite",
        f"INSERT INTO writings VALUES ('Fives, Lille', 'p-lille', 'validated', "
        f"'p1', {AT});",
    )
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        place = registry.place("p-lille")
        [entry] = [e for e in registry.journal() if e.action == "migrate"]
    assert [(lv.name, lv.status) for lv in place.levels][:3] == [
        ("Fives", "proposed"),
        ("Lomme", "proposed"),
        ("Lille", "validated"),
    ]
    assert entry.payload["proposals"] == 3


def test_backup_written_before_migration(tmp_path: Path, ref: RefData) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    PlaceRegistry(tmp_path / "r.sqlite", ref).close()
    [backup] = tmp_path.glob("r.v1-*.sqlite")
    conn = sqlite3.connect(backup)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM place_fields").fetchone()[0] == 9
    conn.close()


def test_backup_path() -> None:
    at = datetime(2026, 11, 8, 14, 5, 9)
    assert backup_path(Path("/d/referentiel.sqlite"), at) == Path(
        "/d/referentiel.v1-20261108T140509.sqlite"
    )


def test_failed_backup_changes_nothing(
    tmp_path: Path, ref: RefData, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "r.sqlite"
    _v1_registry(path)
    monkeypatch.setattr(
        migrate, "backup_path", lambda p, at: tmp_path / "absent" / "b.sqlite"
    )
    with pytest.raises(sqlite3.Error):
        PlaceRegistry(path, ref)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM place_fields").fetchone()[0] == 9
    conn.close()


def test_invalid_chain_rolls_back_and_names_the_place(
    tmp_path: Path, ref: RefData
) -> None:
    path = tmp_path / "r.sqlite"
    _v1_registry(
        path,
        f"INSERT INTO places VALUES ('p-blanc', {AT});"
        "INSERT INTO place_fields VALUES ('p-blanc','commune','  ','manual');",
    )
    with pytest.raises(ValueError, match="p-blanc"):
        PlaceRegistry(path, ref)
    assert len(list(tmp_path.glob("r.v1-*.sqlite"))) == 1
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM place_fields").fetchone()[0] == 10
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "place_levels" not in tables
    conn.close()


def test_place_without_level_is_named_after_its_first_writing(
    tmp_path: Path, ref: RefData
) -> None:
    _v1_registry(
        tmp_path / "r.sqlite",
        f"INSERT INTO places VALUES ('p-cp', {AT});"
        "INSERT INTO place_fields VALUES ('p-cp','postal_code','59000','manual');"
        f"INSERT INTO writings VALUES ('Quai Sud', 'p-cp', 'validated', 'p1', {AT}),"
        f" ('Quai Nord', 'p-cp', 'validated', 'p1', {AT});",
    )
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        place = registry.place("p-cp")
        [entry] = [e for e in registry.journal() if e.action == "migrate"]
    assert [(lv.name, lv.type, lv.origin, lv.status) for lv in place.levels] == [
        ("Quai Nord", None, "written", "validated"),
        ("Quai Sud", None, "written", "proposed"),
    ]
    assert (place.postal_code, place.postal_origin) == ("59000", "manual")
    assert entry.payload["empty"] == 0


def test_place_without_level_nor_writing_stays_empty(
    tmp_path: Path, ref: RefData
) -> None:
    _v1_registry(tmp_path / "r.sqlite", f"INSERT INTO places VALUES ('p-nu', {AT});")
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        assert registry.place("p-nu").levels == ()
        [entry] = [e for e in registry.journal() if e.action == "migrate"]
        assert entry.payload["empty"] == 1 and entry.payload["places"] == 3
        assert "p-nu" not in {k.place_id for k in registry.known_places()}


def test_migration_is_journaled_once_and_idempotent(
    tmp_path: Path, ref: RefData
) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    PlaceRegistry(tmp_path / "r.sqlite", ref).close()
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        entries = [e for e in registry.journal() if e.action == "migrate"]
        assert len(entries) == 1 and entries[0].payload["places"] == 2
        [backup] = tmp_path.glob("r.v1-*.sqlite")
        assert entries[0].project is None
        assert entries[0].payload == {
            "from": 1,
            "to": 2,
            "backup": backup.name,
            "places": 2,
            "proposals": 2,
            "empty": 0,
        }
        with pytest.raises(ValueError, match="sauvegarde"):
            registry.undo(entries[0].entry_id)
    assert len(list(tmp_path.glob("r.v1-*.sqlite"))) == 1


def test_v1_journal_is_kept_and_no_longer_undone(tmp_path: Path, ref: RefData) -> None:
    payload = (
        '{"rows": [{"table": "place_fields", "key": {"place_id": "p-lille", '
        '"kind": "commune"}, "before": null, "after": {"value": "Lille", '
        '"origin": "reference"}}], "details": {}}'
    )
    _v1_registry(
        tmp_path / "r.sqlite",
        f"INSERT INTO journal (at, project, action, payload) "
        f"VALUES ({AT}, 'p1', 'validate', '{payload}');",
    )
    with PlaceRegistry(tmp_path / "r.sqlite", ref) as registry:
        old, migrated = sorted(registry.journal(), key=lambda e: e.entry_id)
        assert (old.action, migrated.action) == ("validate", "migrate")
        assert old.entry_id == 1 and migrated.entry_id == 2
        with pytest.raises(ValueError, match="migration"):
            registry.undo(old.entry_id)
        place_id = registry.validate(
            ["Roubaix"], (Level(0, "Roubaix"),), None, None, "p1"
        ).place_id
        entry = registry.journal()[0].entry_id
        registry.undo(entry)
        with pytest.raises(KeyError):
            registry.place(place_id)


def test_v1_without_reference_data(tmp_path: Path) -> None:
    _v1_registry(tmp_path / "r.sqlite")
    with pytest.raises(SchemaVersionError, match="migr"):
        PlaceRegistry(tmp_path / "r.sqlite")
    assert list(tmp_path.glob("r.v1-*.sqlite")) == []


# --- levels_from_v1 ---------------------------------------------------------------


def test_levels_from_v1_renamed_commune_goes_to_written(ref: RefData) -> None:
    levels, postal, origin = levels_from_v1(
        {
            "commune": "Saint-Omer",
            "insee_code": "62765",
            "former_name": "Saint-Omer-en-Artois",
        },
        {"commune": "manual", "insee_code": "manual", "former_name": "rule"},
        ref,
    )
    assert levels == (
        Level(
            0,
            "Saint-Omer",
            written="Saint-Omer-en-Artois",
            type="commune",
            identifier="62765",
            origin="manual",
        ),
    )
    assert (postal, origin) == (None, None)


def test_levels_from_v1_unknown_former_name_is_an_untyped_proposal(
    ref: RefData,
) -> None:
    levels, _, _ = levels_from_v1(
        {"commune": "Lille", "insee_code": "59350", "former_name": "Vieux-Lille"},
        {"commune": "rule", "insee_code": "rule", "former_name": "rule"},
        ref,
    )
    assert [(lv.rank, lv.name, lv.type, lv.status, lv.origin) for lv in levels] == [
        (0, "Vieux-Lille", None, "proposed", "written"),
        (1, "Lille", "commune", "validated", "rule"),
    ]


def test_levels_from_v1_department_name_region_and_llm_origin(ref: RefData) -> None:
    levels, postal, origin = levels_from_v1(
        {
            "department": "Nord",
            "region": "Nord-Pas-de-Calais",
            "postal_code": "59000",
        },
        {"department": "llm", "region": "manual", "postal_code": "reference"},
        ref,
    )
    assert [(lv.name, lv.type, lv.identifier, lv.origin) for lv in levels] == [
        ("Nord", "departement", "59", "llm"),
        ("Nord-Pas-de-Calais", "ancienne_region", None, "manual"),
    ]
    assert (postal, origin) == ("59000", "insee")


def test_levels_from_v1_commune_from_insee_code_only(ref: RefData) -> None:
    levels, _, _ = levels_from_v1(
        {"insee_code": "59350"}, {"insee_code": "reference"}, ref
    )
    assert [(lv.name, lv.type, lv.identifier, lv.origin) for lv in levels] == [
        ("Lille", "commune", "59350", "insee")
    ]


@pytest.mark.parametrize(
    ("origins", "message"),
    [
        ({}, "manquante"),
        ({"commune": "reference", "postal_code": "oracle"}, "inconnue"),
    ],
)
def test_levels_from_v1_origin_errors_are_value_errors(
    ref: RefData, origins: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        levels_from_v1({"commune": "Lille", "postal_code": "59000"}, origins, ref)
