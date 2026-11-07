import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from prosopo_gw_atelier.places.cluster import build_clusters, name_key
from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.refdata import load_refdata
from prosopo_gw_atelier.store import paths
from prosopo_gw_atelier.store.registry import (
    Decision,
    PlaceRegistry,
    RowChange,
    SchemaVersionError,
)

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "refdata_mini"

ROUBAIX = {"commune": "Roubaix", "department": "59", "insee_code": "59512"}
RULE = {"commune": "rule", "department": "rule", "insee_code": "rule"}


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


# --- Step 1: validate, undo, reject, correct --------------------------------


def test_validate_attaches_all_writings_to_one_place(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix", "ROUBAIX"], ROUBAIX, RULE, "proj")
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
    place = registry.place(place_id)
    assert place.fields == ROUBAIX
    assert place.origins == RULE


def test_undo_validate_forgets_the_decisions(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix", "ROUBAIX"], ROUBAIX, RULE, "proj")
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


def test_reject(registry: PlaceRegistry) -> None:
    registry.reject(["en mer"], "proj")
    assert registry.decision("en mer") == Decision("en mer", None, "rejected", "proj")
    assert registry.journal()[0].action == "reject"


def test_correct_changes_field_and_origin(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "proj")
    registry.correct(place_id, "commune", "Roubaix-Ville", "proj")
    place = registry.place(place_id)
    assert place.fields["commune"] == "Roubaix-Ville"
    assert place.origins["commune"] == "manual"
    assert place.origins["department"] == "rule"
    assert registry.journal()[0].action == "correct"


def test_undo_correct_restores_field_and_origin(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "proj")
    registry.correct(place_id, "commune", "Roubaix-Ville", "proj")
    registry.undo(registry.journal()[0].entry_id)
    place = registry.place(place_id)
    assert place.fields == ROUBAIX
    assert place.origins == RULE


def test_correct_adds_a_missing_field(registry: PlaceRegistry) -> None:
    place_id = registry.validate(
        ["Roubaix"], {"commune": "Roubaix"}, {"commune": "rule"}, "p"
    )
    registry.correct(place_id, "country", "France", "p")
    assert registry.place(place_id).fields == {
        "commune": "Roubaix",
        "country": "France",
    }


def test_correct_unknown_place_raises_key_error(registry: PlaceRegistry) -> None:
    with pytest.raises(KeyError):
        registry.correct("nope", "commune", "X", "p")


def test_place_unknown_raises_key_error(registry: PlaceRegistry) -> None:
    with pytest.raises(KeyError):
        registry.place("nope")


# --- reattachment, detach, decisions ------------------------------------------


def test_validate_existing_place_merges_fields(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "a")
    same = registry.validate(
        ["59100 Roubaix"],
        {"postal_code": "59100", "commune": "Roubaix"},
        {"postal_code": "rule", "commune": "manual"},
        "b",
        place_id=place_id,
    )
    assert same == place_id
    place = registry.place(place_id)
    assert place.fields == {**ROUBAIX, "postal_code": "59100"}
    assert place.origins["commune"] == "manual"
    assert registry.decision("59100 Roubaix") == Decision(
        "59100 Roubaix", place_id, "validated", "b"
    )
    assert registry.decision("Roubaix") == Decision(
        "Roubaix", place_id, "validated", "a"
    )


def test_validate_unknown_place_id_raises_key_error(registry: PlaceRegistry) -> None:
    with pytest.raises(KeyError):
        registry.validate(["X"], {}, {}, "p", place_id="nope")
    assert registry.journal() == []


def test_validate_requires_an_origin_per_field(registry: PlaceRegistry) -> None:
    with pytest.raises(ValueError):
        registry.validate(["X"], {"commune": "X"}, {}, "p")
    with pytest.raises(ValueError):
        registry.validate([], {"commune": "X"}, {"commune": "rule"}, "p")


def test_reattach_records_previous_row_and_undo_restores_it(
    registry: PlaceRegistry,
) -> None:
    first = registry.validate(["Lile"], {"commune": "Lille"}, {"commune": "rule"}, "a")
    second = registry.validate(
        ["Lille"], {"commune": "Lille"}, {"commune": "rule"}, "b"
    )
    registry.validate(["Lile"], {}, {}, "b", place_id=second)
    entry = registry.journal()[0]
    (row,) = [r for r in entry.payload["rows"] if r["table"] == "writings"]
    assert row["key"] == {"writing": "Lile"}
    assert row["before"]["place_id"] == first
    assert row["after"]["place_id"] == second
    registry.undo(entry.entry_id)
    assert registry.decision("Lile") == Decision("Lile", first, "validated", "a")


def test_reject_validated_writing_then_undo(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Mer"], {"commune": "Mer"}, {"commune": "rule"}, "a")
    registry.reject(["Mer"], "b")
    assert registry.decision("Mer") == Decision("Mer", None, "rejected", "b")
    registry.undo(registry.journal()[0].entry_id)
    assert registry.decision("Mer") == Decision("Mer", place_id, "validated", "a")


def test_detach_makes_writings_undecided_and_keeps_place(
    registry: PlaceRegistry,
) -> None:
    place_id = registry.validate(["Roubaix", "ROUBAIX"], ROUBAIX, RULE, "a")
    registry.detach(["ROUBAIX"], "a")
    assert registry.decision("ROUBAIX") is None
    assert registry.decision("Roubaix") is not None
    assert registry.place(place_id).fields == ROUBAIX
    assert registry.journal()[0].action == "detach"
    registry.undo(registry.journal()[0].entry_id)
    assert registry.decision("ROUBAIX") == Decision(
        "ROUBAIX", place_id, "validated", "a"
    )


def test_decisions_returns_only_decided(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "a")
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
    with pytest.raises(ValueError):
        registry.undo(original)
    with pytest.raises(ValueError):
        registry.undo(registry.journal()[0].entry_id)
    with pytest.raises(ValueError):
        registry.undo(9999)


def test_undo_conflicting_with_later_entry_raises(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "p")
    first = registry.journal()[0].entry_id
    registry.reject(["Roubaix"], "p")
    later = registry.journal()[0].entry_id
    with pytest.raises(ValueError, match=f"entry {later}"):
        registry.undo(first)
    assert registry.decision("Roubaix") == Decision("Roubaix", None, "rejected", "p")
    assert registry.place(place_id).fields == ROUBAIX
    # Undoing the later one first makes the older one undoable again.
    registry.undo(later)
    registry.undo(first)
    assert registry.decision("Roubaix") is None


def test_undo_place_creation_conflicts_with_later_attachment(
    registry: PlaceRegistry,
) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "p")
    first = registry.journal()[0].entry_id
    registry.validate(["ROUBAIX"], {}, {}, "p", place_id=place_id)
    later = registry.journal()[0].entry_id
    with pytest.raises(ValueError, match=f"entry {later}"):
        registry.undo(first)
    assert registry.decision("Roubaix") is not None


# --- import hook (for Task 9) ---------------------------------------------------


def test_apply_import_is_journaled_and_undoable(registry: PlaceRegistry) -> None:
    entry_id = registry.apply_import(
        [
            RowChange(
                "places",
                {"place_id": "p-1"},
                {"created_at": "2026-01-01T00:00:00+00:00"},
            ),
            RowChange(
                "place_fields",
                {"place_id": "p-1", "kind": "commune"},
                {"value": "Lille", "origin": "reference"},
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
    assert registry.place("p-1").origins == {"commune": "reference"}
    assert registry.decision("Lille") == Decision("Lille", "p-1", "validated", None)
    registry.undo(entry_id)
    assert registry.decision("Lille") is None
    with pytest.raises(KeyError):
        registry.place("p-1")


# --- transactions ---------------------------------------------------------


def test_failure_mid_transaction_writes_nothing(
    registry: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(registry, "_append_journal", boom)
    with pytest.raises(RuntimeError):
        registry.validate(["Roubaix"], ROUBAIX, RULE, "p")
    monkeypatch.undo()
    assert registry.decision("Roubaix") is None
    assert registry.known_places() == []
    assert registry.journal() == []


# --- Step 2: file creation, schema version, concurrency ---------------------


def test_creates_missing_file_and_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "ref.sqlite"
    with PlaceRegistry(path) as reg:
        assert reg.journal() == []
    assert path.exists()
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    con.close()


def test_reopen_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "ref.sqlite"
    with PlaceRegistry(path) as reg:
        place_id = reg.validate(["Roubaix"], ROUBAIX, RULE, "p")
    with PlaceRegistry(path) as reg:
        assert reg.place(place_id).fields == ROUBAIX


def test_newer_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "ref.sqlite"
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 2")
    con.close()
    with pytest.raises(SchemaVersionError, match="version 2"):
        PlaceRegistry(path)


def test_two_registries_alternate_writes(tmp_path: Path) -> None:
    path = tmp_path / "ref.sqlite"
    with PlaceRegistry(path) as one, PlaceRegistry(path) as two:
        for i in range(20):
            reg = one if i % 2 == 0 else two
            reg.validate(
                [f"Ville {i}"], {"commune": f"Ville {i}"}, {"commune": "rule"}, "p"
            )
            other = two if reg is one else one
            assert other.decision(f"Ville {i}") is not None
        assert len(one.journal()) == 20
        one.undo(two.journal()[0].entry_id)
        assert two.decision("Ville 19") is None


# --- known places and clustering ------------------------------------------------


def test_known_places_anchor_fresh_clusters(registry: PlaceRegistry) -> None:
    ref = load_refdata(MINI)
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "p")
    known = registry.known_places()
    assert [(k.place_id, k.insee, k.name_key) for k in known] == [
        (place_id, "59512", name_key("Roubaix"))
    ]
    writing = "Roubaix (Nord)"
    clusters = build_clusters(
        {writing: decompose(writing, ref)}, ref, {k.place_id: k for k in known}
    )
    (cluster,) = clusters
    assert cluster.anchor_place_id == place_id


def test_known_place_without_insee_anchors_by_name(registry: PlaceRegistry) -> None:
    ref = load_refdata(MINI)
    place_id = registry.validate(
        ["Saint-Inconnu"], {"commune": "Saint-Inconnu"}, {"commune": "manual"}, "p"
    )
    known = {k.place_id: k for k in registry.known_places()}
    assert known[place_id].insee is None
    (cluster,) = build_clusters(
        {"SAINT INCONNU": decompose("SAINT INCONNU", ref)}, ref, known
    )
    assert cluster.anchor_place_id == place_id


# --- removing fields ------------------------------------------------------------


def test_validate_with_none_removes_the_field(registry: PlaceRegistry) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "p")
    registry.validate(
        ["Roubaix"],
        {"commune": "Roubaix", "department": None},
        {"commune": "rule"},
        "p",
        place_id,
    )
    place = registry.place(place_id)
    assert "department" not in place.fields
    assert "department" not in place.origins
    entry = registry.journal()[0]
    (row,) = [r for r in entry.payload["rows"] if r["key"].get("kind") == "department"]
    assert row["before"] == {"value": "59", "origin": "rule"}
    assert row["after"] is None
    registry.undo(entry.entry_id)
    place = registry.place(place_id)
    assert place.fields == ROUBAIX
    assert place.origins == RULE


def test_validate_none_on_a_new_place_is_ignored(registry: PlaceRegistry) -> None:
    place_id = registry.validate(
        ["Roubaix"], {"commune": "Roubaix", "region": None}, {"commune": "rule"}, "p"
    )
    assert registry.place(place_id).fields == {"commune": "Roubaix"}


def test_validate_rejects_an_origin_for_a_removed_field(
    registry: PlaceRegistry,
) -> None:
    with pytest.raises(ValueError):
        registry.validate(["X"], {"commune": None}, {"commune": "rule"}, "p")


def test_correct_with_none_removes_the_field_and_undo_restores_it(
    registry: PlaceRegistry,
) -> None:
    place_id = registry.validate(["Roubaix"], ROUBAIX, RULE, "p")
    registry.correct(place_id, "department", None, "p")
    assert registry.place(place_id).fields == {
        "commune": "Roubaix",
        "insee_code": "59512",
    }
    entry = registry.journal()[0]
    assert entry.action == "correct"
    registry.undo(entry.entry_id)
    place = registry.place(place_id)
    assert place.fields == ROUBAIX
    assert place.origins == RULE
