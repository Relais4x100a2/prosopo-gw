import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from prosopo_gw_atelier.places.cluster import KnownPlace, build_clusters, name_key
from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.levels import Level, renumber
from prosopo_gw_atelier.refdata import load_refdata
from prosopo_gw_atelier.store import paths
from prosopo_gw_atelier.store.registry import (
    Decision,
    PlaceRegistry,
    PrecisionDecision,
    RowChange,
    SchemaVersionError,
)

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "refdata_mini"

LILLE = (
    Level(0, "Lille", type="commune", identifier="59350", origin="insee"),
    Level(1, "Nord", type="departement", identifier="59", origin="insee"),
    Level(2, "France", type="pays", origin="written"),
)
ROUBAIX = (
    Level(0, "Roubaix", type="commune", identifier="59512", origin="rule"),
    Level(1, "Nord", type="departement", identifier="59", origin="rule"),
)


def chain(*names: str) -> tuple[Level, ...]:
    """Untyped manual chain, one level per name."""
    return renumber([Level(0, name, origin="manual") for name in names])


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "ref.sqlite") as reg:
        yield reg


# --- paths ---------------------------------------------------------------


def test_data_dir_honours_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROSOPO_GW_ATELIER_HOME", str(tmp_path / "home"))
    assert paths.data_dir() == tmp_path / "home"
    assert paths.registry_path() == tmp_path / "home" / "referentiel.sqlite"


def test_data_dir_defaults_to_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    import platformdirs

    monkeypatch.delenv("PROSOPO_GW_ATELIER_HOME", raising=False)
    assert paths.data_dir() == Path(platformdirs.user_data_dir("prosopo-gw-atelier"))


# --- level chains ---------------------------------------------------------------


def test_validate_stores_levels(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, "59000", "written", "p1")
    place = registry.place(v.place_id)
    assert place.levels == LILLE and place.postal_code == "59000"
    assert place.postal_origin == "written"
    assert place.fields["insee_code"] == "59350"


def test_validate_keeps_every_level_attribute(registry: PlaceRegistry) -> None:
    full = (
        Level(
            0,
            "Marconne",
            written="MARCONNE",
            type="commune_historique",
            identifier="62549",
            source="COG 2026",
            start="1790-01-01",
            end="2025-01-01",
            latitude=50.37,
            longitude=2.04,
            nature="deleguee",
            origin="insee",
        ),
        Level(1, "Artois", origin="written", status="proposed"),
    )
    v = registry.validate(["MARCONNE"], full, None, None, "p1")
    assert registry.place(v.place_id).levels == full


def test_set_levels_and_undo_restores_reordered_chain(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, None, None, "p1")
    reordered = renumber((Level(0, "Fives", origin="manual"), *LILLE))
    entry = registry.set_levels(v.place_id, reordered, None, None, "p1")
    assert [lv.name for lv in registry.place(v.place_id).levels] == [
        "Fives",
        "Lille",
        "Nord",
        "France",
    ]
    assert entry is not None
    assert registry.journal()[0].action == "correct"
    registry.undo(entry)
    assert registry.place(v.place_id).levels == LILLE


def test_set_levels_shortens_the_chain_and_sets_postal_code(
    registry: PlaceRegistry,
) -> None:
    v = registry.validate(["LILLE"], LILLE, None, None, "p1")
    registry.set_levels(v.place_id, LILLE[:1], "59000", "manual", "p1")
    place = registry.place(v.place_id)
    assert place.levels == LILLE[:1]
    assert (place.postal_code, place.postal_origin) == ("59000", "manual")
    entry = registry.journal()[0]
    removed = [r for r in entry.payload["rows"] if r["after"] is None]
    assert sorted(r["key"]["rank"] for r in removed) == [1, 2]
    registry.undo(entry.entry_id)
    place = registry.place(v.place_id)
    assert place.levels == LILLE
    assert place.postal_code is None


def test_set_levels_removes_the_postal_code(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, "59000", "written", "p1")
    registry.set_levels(v.place_id, LILLE, None, None, "p1")
    place = registry.place(v.place_id)
    assert place.postal_code is None and place.postal_origin is None
    assert "postal_code" not in place.fields


def test_set_levels_unchanged_journals_nothing(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, None, None, "p1")
    assert registry.set_levels(v.place_id, LILLE, None, None, "p1") is None


def test_set_levels_unknown_place_raises_key_error(registry: PlaceRegistry) -> None:
    with pytest.raises(KeyError):
        registry.set_levels("nope", LILLE, None, None, "p")


def test_set_levels_rejects_invalid_chain(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, None, None, "p1")
    with pytest.raises(ValueError):
        registry.set_levels(v.place_id, (), None, None, "p1")
    assert registry.place(v.place_id).levels == LILLE


def test_accept_and_refuse_proposal(registry: PlaceRegistry) -> None:
    proposed = (*LILLE, Level(3, "Flandre", status="proposed", origin="written"))
    v = registry.validate(["LILLE"], proposed, None, None, "p1")
    registry.accept_proposal(v.place_id, 3, "p1")
    assert registry.place(v.place_id).levels[3].status == "validated"
    v2 = registry.validate(
        ["LOMME"],
        renumber((Level(0, "Lomme", status="proposed"), *LILLE)),
        None,
        None,
        "p1",
    )
    registry.refuse_proposal(v2.place_id, 0, "p1")
    assert [lv.rank for lv in registry.place(v2.place_id).levels] == [0, 1, 2]


def test_refuse_proposal_is_journaled_and_undone(registry: PlaceRegistry) -> None:
    lomme = renumber((Level(0, "Lomme", status="proposed"), *LILLE))
    v = registry.validate(["LOMME"], lomme, None, None, "p1")
    entry = registry.refuse_proposal(v.place_id, 0, "p1")
    assert entry is not None
    assert registry.place(v.place_id).levels == LILLE
    assert registry.journal()[0].action == "correct"
    registry.undo(entry)
    assert registry.place(v.place_id).levels == lomme


def test_accept_proposal_is_undone(registry: PlaceRegistry) -> None:
    proposed = (*LILLE, Level(3, "Flandre", status="proposed", origin="written"))
    v = registry.validate(["LILLE"], proposed, None, None, "p1")
    entry = registry.accept_proposal(v.place_id, 3, "p1")
    assert entry is not None
    assert registry.journal()[0].action == "correct"
    registry.undo(entry)
    assert registry.place(v.place_id).levels == proposed


def test_proposal_must_exist_and_be_proposed(registry: PlaceRegistry) -> None:
    v = registry.validate(["LILLE"], LILLE, None, None, "p1")
    with pytest.raises(ValueError):
        registry.accept_proposal(v.place_id, 0, "p1")
    with pytest.raises(ValueError):
        registry.refuse_proposal(v.place_id, 0, "p1")
    with pytest.raises(ValueError):
        registry.accept_proposal(v.place_id, 9, "p1")
    with pytest.raises(KeyError):
        registry.refuse_proposal("nope", 0, "p1")
    assert registry.place(v.place_id).levels == LILLE


def test_validate_rejects_invalid_chain(registry: PlaceRegistry) -> None:
    with pytest.raises(ValueError):
        registry.validate(["X"], (Level(0, ""),), None, None, "p1")
    assert registry.decisions(["X"]) == {}


def test_validate_rejects_unknown_level_values(registry: PlaceRegistry) -> None:
    bad_origin = replace(LILLE[0], origin="reference")  # type: ignore[arg-type]
    bad_status = replace(LILLE[0], status="maybe")  # type: ignore[arg-type]
    bad_nature = replace(LILLE[0], nature="renommage")  # type: ignore[arg-type]
    for level in (bad_origin, bad_status, bad_nature):
        with pytest.raises(ValueError):
            registry.validate(["X"], (level,), None, None, "p1")
    assert registry.journal() == []


def test_validate_requires_postal_code_and_origin_together(
    registry: PlaceRegistry,
) -> None:
    with pytest.raises(ValueError):
        registry.validate(["X"], LILLE, "59000", None, "p1")
    with pytest.raises(ValueError):
        registry.validate(["X"], LILLE, None, "written", "p1")
    with pytest.raises(ValueError):
        registry.validate(["X"], LILLE, "59000", "paris", "p1")
    assert registry.journal() == []


def test_known_places_historical(registry: PlaceRegistry) -> None:
    historical = (
        Level(
            0,
            "Marconne",
            type="commune_historique",
            identifier="62549",
            nature="deleguee",
            origin="insee",
        ),
        Level(1, "Hesdin-la-Forêt", type="commune", identifier="62447", origin="insee"),
    )
    v = registry.validate(["Marconne"], historical, None, None, "p1")
    [known] = registry.known_places()
    assert known == KnownPlace(v.place_id, None, "marconne", None, "62549|marconne")


def test_known_places_read_validated_levels_only(registry: PlaceRegistry) -> None:
    proposed = renumber(
        (
            Level(
                0,
                "Fives",
                type="commune_historique",
                identifier="59999",
                status="proposed",
            ),
            *LILLE,
        )
    )
    v = registry.validate(["LILLE"], proposed, None, None, "p1")
    assert registry.known_places() == [
        KnownPlace(v.place_id, "59350", name_key("Lille"), "59")
    ]


def test_known_places_key_on_the_commune_after_a_sub_level(
    registry: PlaceRegistry,
) -> None:
    fives = renumber((Level(0, "Fives", origin="written"), *LILLE))
    v = registry.validate(["Fives, Lille"], fives, None, None, "p1")
    assert registry.known_places() == [
        KnownPlace(v.place_id, "59350", name_key("Lille"), "59", finer="fives")
    ]


def test_known_places_sub_level_before_a_historical_commune(
    registry: PlaceRegistry,
) -> None:
    levels = renumber(
        (
            Level(0, "Canteleu", origin="written"),
            Level(
                0,
                "Lomme",
                type="commune_historique",
                identifier="59355",
                nature="associee",
                origin="insee",
            ),
            *LILLE,
        )
    )
    v = registry.validate(["Canteleu, Lomme"], levels, None, None, "p1")
    assert registry.known_places() == [
        KnownPlace(v.place_id, None, "lomme", "59", "59355|lomme", "canteleu")
    ]


def test_known_places_key_on_the_first_level_without_commune(
    registry: PlaceRegistry,
) -> None:
    v = registry.validate(["Winnipeg"], chain("Winnipeg", "Canada"), None, None, "p")
    assert registry.known_places() == [
        KnownPlace(v.place_id, None, name_key("Winnipeg"), None)
    ]


def test_known_places_skip_historical_commune_without_code(
    registry: PlaceRegistry,
) -> None:
    historical = (
        Level(0, "Marconne", type="commune_historique", origin="manual"),
        Level(1, "Hesdin-la-Forêt", type="commune", identifier="62447"),
    )
    registry.validate(["Marconne"], historical, None, None, "p1")
    assert registry.known_places() == []


def test_new_registry_is_version_3(tmp_path: Path) -> None:
    PlaceRegistry(tmp_path / "r.sqlite").close()
    con = sqlite3.connect(tmp_path / "r.sqlite")
    assert con.execute("PRAGMA user_version").fetchone()[0] == 3
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    assert {"place_levels", "place_attributes", "precisions"} <= tables
    assert "place_fields" not in tables
    con.close()


def test_journal_accepts_the_migrate_action(tmp_path: Path) -> None:
    PlaceRegistry(tmp_path / "r.sqlite").close()
    con = sqlite3.connect(tmp_path / "r.sqlite")
    con.execute(
        "INSERT INTO journal (at, action, payload) VALUES ('x', 'migrate', '{}')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO journal (at, action, payload) VALUES ('x', 'other', '{}')"
        )
    con.close()


def test_version_1_file_requires_reference_data(tmp_path: Path) -> None:
    path = tmp_path / "ref.sqlite"
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 1")
    con.close()
    with pytest.raises(SchemaVersionError, match="données de référence"):
        PlaceRegistry(path)


# --- validate, undo, reject, detach ---------------------------------------------


def test_validate_attaches_all_writings_to_one_place(registry: PlaceRegistry) -> None:
    place_id = registry.validate(
        ["Roubaix", "ROUBAIX"], ROUBAIX, None, None, "proj"
    ).place_id
    uuid.UUID(place_id, version=4)
    assert registry.decision("Roubaix") == Decision(
        "Roubaix", place_id, "validated", "proj"
    )
    assert registry.decision("ROUBAIX") == Decision(
        "ROUBAIX", place_id, "validated", "proj"
    )
    journal = registry.journal()
    assert [e.action for e in journal] == ["validate"]
    assert journal[0].project == "proj"
    assert not journal[0].undone
    assert registry.place(place_id).levels == ROUBAIX


def test_mutations_return_their_journal_entry(registry: PlaceRegistry) -> None:
    def latest() -> int:
        return registry.journal(limit=1)[0].entry_id

    validated = registry.validate(["Roubaix"], ROUBAIX, None, None, "p")
    assert validated.entry_id == latest()
    assert registry.reject(["En mer"], "p") == latest()
    assert (
        registry.set_levels(validated.place_id, chain("Ville"), None, None, "p")
        == latest()
    )
    detached = registry.detach(["Roubaix"], "p")
    assert detached == latest()
    assert detached is not None
    assert registry.undo(detached) == latest()
    # Nothing changes, nothing is journaled.
    assert registry.detach(["Nulle part"], "p") is None


def test_undo_validate_forgets_the_decisions(registry: PlaceRegistry) -> None:
    place_id = registry.validate(
        ["Roubaix", "ROUBAIX"], ROUBAIX, "59100", "written", "proj"
    ).place_id
    (entry,) = registry.journal()
    registry.undo(entry.entry_id)
    assert registry.decision("Roubaix") is None
    assert registry.decision("ROUBAIX") is None
    with pytest.raises(KeyError):
        registry.place(place_id)
    journal = registry.journal()
    assert [e.action for e in journal] == ["undo", "validate"]
    assert journal[0].payload["undone_entry"] == entry.entry_id
    assert journal[1].undone
    assert registry.places() == []


def test_reject(registry: PlaceRegistry) -> None:
    registry.reject(["en mer"], "proj")
    assert registry.decision("en mer") == Decision("en mer", None, "rejected", "proj")
    assert registry.journal()[0].action == "reject"


def test_place_unknown_raises_key_error(registry: PlaceRegistry) -> None:
    with pytest.raises(KeyError):
        registry.place("nope")


def test_places_lists_every_place_with_its_chain(registry: PlaceRegistry) -> None:
    lille = registry.validate(["LILLE"], LILLE, "59000", "written", "p").place_id
    roubaix = registry.validate(["Roubaix"], ROUBAIX, None, None, "p").place_id
    by_id = {place.place_id: place for place in registry.places()}
    assert by_id[lille].levels == LILLE
    assert by_id[lille].postal_code == "59000"
    assert by_id[roubaix].levels == ROUBAIX
    assert by_id[roubaix].postal_code is None


# --- reattachment, detach, decisions ------------------------------------------


def test_validate_existing_place_replaces_its_chain(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, None, None, "a").place_id
    same = registry.validate(
        ["59100 Roubaix"], ROUBAIX[:1], "59100", "written", "b", place_id=place_id
    ).place_id
    assert same == place_id
    place = registry.place(place_id)
    assert place.levels == ROUBAIX[:1]
    assert place.postal_code == "59100"
    assert registry.decision("59100 Roubaix") == Decision(
        "59100 Roubaix", place_id, "validated", "b"
    )
    assert registry.decision("Roubaix") == Decision(
        "Roubaix", place_id, "validated", "a"
    )


def test_validate_unknown_place_id_raises_key_error(registry: PlaceRegistry) -> None:
    with pytest.raises(KeyError):
        registry.validate(["X"], chain("X"), None, None, "p", place_id="nope")
    assert registry.journal() == []


def test_validate_requires_a_writing(registry: PlaceRegistry) -> None:
    with pytest.raises(ValueError):
        registry.validate([], chain("X"), None, None, "p")


def test_reattach_records_previous_row_and_undo_restores_it(
    registry: PlaceRegistry,
) -> None:
    first = registry.validate(["Lile"], chain("Lille"), None, None, "a").place_id
    second = registry.validate(["Lille"], chain("Lille"), None, None, "b").place_id
    registry.validate(["Lile"], chain("Lille"), None, None, "b", place_id=second)
    entry = registry.journal()[0]
    (row,) = [r for r in entry.payload["rows"] if r["table"] == "writings"]
    assert row["key"] == {"writing": "Lile"}
    assert row["before"]["place_id"] == first
    assert row["after"]["place_id"] == second
    registry.undo(entry.entry_id)
    assert registry.decision("Lile") == Decision("Lile", first, "validated", "a")


def test_reject_validated_writing_then_undo(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Mer"], chain("Mer"), None, None, "a").place_id
    registry.reject(["Mer"], "b")
    assert registry.decision("Mer") == Decision("Mer", None, "rejected", "b")
    registry.undo(registry.journal()[0].entry_id)
    assert registry.decision("Mer") == Decision("Mer", place_id, "validated", "a")


def test_detach_makes_writings_undecided_and_keeps_place(
    registry: PlaceRegistry,
) -> None:
    place_id = registry.validate(
        ["Roubaix", "ROUBAIX"], ROUBAIX, None, None, "a"
    ).place_id
    registry.detach(["ROUBAIX"], "a")
    assert registry.decision("ROUBAIX") is None
    assert registry.decision("Roubaix") is not None
    assert registry.place(place_id).levels == ROUBAIX
    assert registry.journal()[0].action == "detach"
    registry.undo(registry.journal()[0].entry_id)
    assert registry.decision("ROUBAIX") == Decision(
        "ROUBAIX", place_id, "validated", "a"
    )


def test_decisions_returns_only_decided(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, None, None, "a").place_id
    registry.reject(["en mer"], "a")
    assert registry.decisions(["Roubaix", "en mer", "Lille"]) == {
        "Roubaix": Decision("Roubaix", place_id, "validated", "a"),
        "en mer": Decision("en mer", None, "rejected", "a"),
    }


def test_journal_limit_returns_latest_first(registry: PlaceRegistry) -> None:
    registry.reject(["a"], "p")
    registry.reject(["b"], "p")
    registry.reject(["c"], "p")
    journal = registry.journal(limit=2)
    assert [e.payload["rows"][0]["key"]["writing"] for e in journal] == ["c", "b"]
    assert journal[0].at.endswith("+00:00")


# --- undo rules -----------------------------------------------------------


def test_undo_twice_or_undo_of_undo_raises(registry: PlaceRegistry) -> None:
    registry.reject(["en mer"], "p")
    original = registry.journal()[0].entry_id
    registry.undo(original)
    with pytest.raises(ValueError, match="déjà annulée"):
        registry.undo(original)
    with pytest.raises(ValueError, match="est une annulation"):
        registry.undo(registry.journal()[0].entry_id)
    with pytest.raises(ValueError, match="Aucune entrée 9999"):
        registry.undo(9999)


def test_undo_conflicting_with_later_entry_raises(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, None, None, "p").place_id
    first = registry.journal()[0].entry_id
    registry.reject(["Roubaix"], "p")
    later = registry.journal()[0].entry_id
    with pytest.raises(ValueError, match=f"Impossible d'annuler .*entrée {later}"):
        registry.undo(first)
    assert registry.decision("Roubaix") == Decision("Roubaix", None, "rejected", "p")
    assert registry.place(place_id).levels == ROUBAIX
    # Undoing the later one first makes the older one undoable again.
    registry.undo(later)
    registry.undo(first)
    assert registry.decision("Roubaix") is None


def test_undo_conflicting_with_later_level_change_raises(
    registry: PlaceRegistry,
) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, None, None, "p").place_id
    first = registry.set_levels(place_id, chain("Roubaix"), None, None, "p")
    later = registry.set_levels(place_id, chain("Roubaix-Ville"), None, None, "p")
    assert first is not None
    with pytest.raises(ValueError, match=f"Impossible d'annuler .*entrée {later}"):
        registry.undo(first)
    assert registry.place(place_id).levels == chain("Roubaix-Ville")


def test_undo_place_creation_conflicts_with_later_attachment(
    registry: PlaceRegistry,
) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, None, None, "p").place_id
    first = registry.journal()[0].entry_id
    registry.validate(["ROUBAIX"], ROUBAIX, None, None, "p", place_id=place_id)
    later = registry.journal()[0].entry_id
    with pytest.raises(ValueError, match=f"Impossible d'annuler .*entrée {later}"):
        registry.undo(first)
    assert registry.decision("Roubaix") is not None


def test_undo_place_creation_conflicts_with_later_level(
    registry: PlaceRegistry,
) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX[:1], None, None, "p").place_id
    first = registry.journal()[0].entry_id
    later = registry.set_levels(place_id, ROUBAIX, None, None, "p")
    with pytest.raises(ValueError, match=f"Impossible d'annuler .*entrée {later}"):
        registry.undo(first)


# --- import hook ----------------------------------------------------------------


def test_apply_import_is_journaled_and_undoable(registry: PlaceRegistry) -> None:
    entry_id = registry.apply_import(
        [
            RowChange(
                "places",
                {"place_id": "p-1"},
                {"created_at": "2026-01-01T00:00:00+00:00"},
            ),
            RowChange(
                "place_levels",
                {"place_id": "p-1", "rank": 0},
                {
                    "name": "Lille",
                    "written": None,
                    "type": "commune",
                    "identifier": "59350",
                    "source": "COG 2026",
                    "start": None,
                    "end": None,
                    "latitude": None,
                    "longitude": None,
                    "nature": None,
                    "origin": "insee",
                    "status": "validated",
                },
            ),
            RowChange(
                "place_attributes",
                {"place_id": "p-1", "name": "postal_code"},
                {"value": "59000", "origin": "written"},
            ),
            RowChange(
                "writings",
                {"writing": "Lille"},
                {
                    "place_id": "p-1",
                    "status": "validated",
                    "project": None,
                    "decided_at": "2026-01-01T00:00:00+00:00",
                },
            ),
        ],
        project="proj",
        details={"source": "export.json"},
    )
    entry = registry.journal()[0]
    assert entry.entry_id == entry_id
    assert entry.action == "import"
    assert entry.payload["details"] == {"source": "export.json"}
    place = registry.place("p-1")
    assert place.levels == (
        Level(
            0,
            "Lille",
            type="commune",
            identifier="59350",
            source="COG 2026",
            origin="insee",
        ),
    )
    assert (place.postal_code, place.postal_origin) == ("59000", "written")
    assert registry.decision("Lille") == Decision("Lille", "p-1", "validated", None)
    registry.undo(entry_id)
    assert registry.decision("Lille") is None
    with pytest.raises(KeyError):
        registry.place("p-1")


def test_apply_import_rejects_unknown_table(registry: PlaceRegistry) -> None:
    with pytest.raises(ValueError):
        registry.apply_import(
            [RowChange("place_fields", {"place_id": "p", "kind": "commune"}, None)],
            project="p",
        )


# --- transactions ---------------------------------------------------------


def test_failure_mid_transaction_writes_nothing(
    registry: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(registry, "_append_journal", boom)
    with pytest.raises(RuntimeError):
        registry.validate(["Roubaix"], ROUBAIX, None, None, "p")
    monkeypatch.undo()
    assert registry.decision("Roubaix") is None
    assert registry.known_places() == []
    assert registry.places() == []
    assert registry.journal() == []


# --- file creation, schema version, concurrency ---------------------------------


def test_creates_missing_file_and_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "ref.sqlite"
    with PlaceRegistry(path) as reg:
        assert reg.journal() == []
    assert path.exists()
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 3
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    con.close()


def test_reopen_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "ref.sqlite"
    with PlaceRegistry(path) as reg:
        place_id = reg.validate(["Roubaix"], ROUBAIX, "59100", "written", "p").place_id
    with PlaceRegistry(path) as reg:
        place = reg.place(place_id)
        assert place.levels == ROUBAIX
        assert place.postal_code == "59100"


def test_newer_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "ref.sqlite"
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 4")
    con.close()
    with pytest.raises(SchemaVersionError, match="version 4"):
        PlaceRegistry(path)


def test_two_registries_alternate_writes(tmp_path: Path) -> None:
    path = tmp_path / "ref.sqlite"
    with PlaceRegistry(path) as one, PlaceRegistry(path) as two:
        for i in range(20):
            reg = one if i % 2 == 0 else two
            reg.validate([f"Ville {i}"], chain(f"Ville {i}"), None, None, "p")
            other = two if reg is one else one
            assert other.decision(f"Ville {i}") is not None
        assert len(one.journal()) == 20
        one.undo(two.journal()[0].entry_id)
        assert two.decision("Ville 19") is None


# --- known places and clustering ------------------------------------------------


def test_known_places_anchor_fresh_clusters(registry: PlaceRegistry) -> None:
    ref = load_refdata(MINI)
    place_id = registry.validate(["Roubaix"], ROUBAIX, None, None, "p").place_id
    known = registry.known_places()
    assert known == [KnownPlace(place_id, "59512", name_key("Roubaix"), "59")]
    writing = "Roubaix (Nord)"
    clusters = build_clusters(
        {writing: decompose(writing, ref)}, ref, {k.place_id: k for k in known}
    )
    (cluster,) = clusters
    assert cluster.anchor_place_id == place_id


def test_known_place_without_insee_anchors_by_name(registry: PlaceRegistry) -> None:
    ref = load_refdata(MINI)
    place_id = registry.validate(
        ["Saint-Inconnu"], chain("Saint-Inconnu"), None, None, "p"
    ).place_id
    known = {k.place_id: k for k in registry.known_places()}
    assert known[place_id].insee is None
    (cluster,) = build_clusters(
        {"SAINT INCONNU": decompose("SAINT INCONNU", ref)}, ref, known
    )
    assert cluster.anchor_place_id == place_id


# --- arrondissement precision decisions ------------------------------------------


def test_decide_precision_round_trip(registry: PlaceRegistry) -> None:
    assert registry.precision_decisions() == {}
    entry = registry.decide_precision(
        "Paris 7e", "12, rue de Grenelle", "paris-1860", "75107", "paris-q-2", "p1"
    )
    assert entry is not None
    key = ("Paris 7e", "12, rue de Grenelle", "paris-1860")
    decision = registry.precision_decisions()[key]
    assert decision == PrecisionDecision(
        "Paris 7e",
        "12, rue de Grenelle",
        "paris-1860",
        "75107",
        "paris-q-2",
        "p1",
        decision.decided_at,
    )
    assert decision.decided_at
    [last] = registry.journal()
    assert last.action == "correct"
    assert last.payload["details"]["kind"] == "precision"
    # same decision again: nothing changes, nothing journaled
    assert (
        registry.decide_precision(
            "Paris 7e", "12, rue de Grenelle", "paris-1860", "75107", "paris-q-2", "p1"
        )
        is None
    )
    assert len(registry.journal()) == 1
    # another answer replaces it
    registry.decide_precision(
        "Paris 7e", "12, rue de Grenelle", "paris-1860", "75106", None, "p1"
    )
    assert registry.precision_decisions()[key].arrondissement_id == "75106"
    assert registry.precision_decisions()[key].quartier_id is None


def test_precision_key_uses_empty_complement_and_empty_period(
    registry: PlaceRegistry,
) -> None:
    registry.decide_precision("Paris", None, "", "paris-07", None, "p1")
    assert list(registry.precision_decisions()) == [("Paris", "", "")]
    # None and "" are the same complement
    assert registry.decide_precision("Paris", "", "", "paris-07", None, "p1") is None
    assert registry.clear_precision("Paris", None, "", "p1") is not None
    assert registry.precision_decisions() == {}
    assert registry.clear_precision("Paris", None, "", "p1") is None


def test_no_arrondissement_decision_has_both_ids_empty(
    registry: PlaceRegistry,
) -> None:
    registry.decide_precision("Paris", None, "paris-1860", None, None, "p1")
    decision = registry.precision_decisions()[("Paris", "", "paris-1860")]
    assert (decision.arrondissement_id, decision.quartier_id) == (None, None)


def test_candidate_id_empty_is_normalised_to_no_arrondissement(
    registry: PlaceRegistry,
) -> None:
    # A Task 6 candidate "" means "this number did not exist at that date".
    registry.decide_precision("Paris", None, "paris-1795", "", "", "p1")
    decision = registry.precision_decisions()[("Paris", "", "paris-1795")]
    assert (decision.arrondissement_id, decision.quartier_id) == (None, None)
    con = sqlite3.connect(registry._conn.execute("PRAGMA database_list").fetchone()[2])
    assert con.execute("SELECT arrondissement_id FROM precisions").fetchone() == (None,)
    con.close()


def test_undo_precision_decision(registry: PlaceRegistry) -> None:
    first = registry.decide_precision("Paris", None, "paris-1860", "75107", None, "p")
    assert first is not None
    second = registry.decide_precision("Paris", None, "paris-1860", "75108", None, "p")
    assert second is not None
    with pytest.raises(ValueError, match="annuler"):
        registry.undo(first)  # a later decision changed the row
    registry.undo(second)
    key = ("Paris", "", "paris-1860")
    assert registry.precision_decisions()[key].arrondissement_id == "75107"
    registry.undo(first)
    assert registry.precision_decisions() == {}


def test_undo_clear_precision(registry: PlaceRegistry) -> None:
    registry.decide_precision("Paris", None, "paris-1860", "75107", None, "p")
    cleared = registry.clear_precision("Paris", None, "paris-1860", "p")
    assert cleared is not None
    assert registry.precision_decisions() == {}
    registry.undo(cleared)
    assert list(registry.precision_decisions()) == [("Paris", "", "paris-1860")]


def test_empty_ids_store_the_same_as_none(registry: PlaceRegistry) -> None:
    registry.decide_precision("A", None, "", "", "", "p")
    registry.decide_precision("B", None, "", None, None, "p")
    a = registry.precision_decisions()[("A", "", "")]
    b = registry.precision_decisions()[("B", "", "")]
    assert (a.arrondissement_id, a.quartier_id) == (b.arrondissement_id, b.quartier_id)
    assert (a.arrondissement_id, a.quartier_id) == (None, None)


def test_clear_missing_precision_writes_nothing(registry: PlaceRegistry) -> None:
    assert registry.clear_precision("Paris", None, "", "p") is None
    assert registry.journal() == []
