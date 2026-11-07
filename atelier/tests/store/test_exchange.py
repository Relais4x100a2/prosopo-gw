import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from prosopo_gw_atelier.store import exchange
from prosopo_gw_atelier.store.exchange import (
    FORMAT,
    Conflict,
    RegistryFormatError,
    StaleConflictError,
    export_registry,
    import_registry,
    resolve_conflict,
)
from prosopo_gw_atelier.store.registry import Decision, Place, PlaceRegistry, RowChange

ROUBAIX = {"commune": "Roubaix", "department": "59", "insee_code": "59512"}
ROUBAIX_ORIGINS = {"commune": "rule", "department": "manual", "insee_code": "rule"}
LILLE = {"commune": "Lille", "insee_code": "59350"}
LILLE_ORIGINS = {"commune": "rule", "insee_code": "reference"}


@pytest.fixture
def source(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "source.sqlite") as reg:
        yield reg


@pytest.fixture
def target(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "target.sqlite") as reg:
        yield reg


def _fill(reg: PlaceRegistry) -> tuple[str, str]:
    roubaix = reg.validate(
        ["ROUBAIX", "Roubaix, Nord"],
        ROUBAIX,
        ROUBAIX_ORIGINS,
        "p1",  # type: ignore[arg-type]
    ).place_id
    lille = reg.validate(["Lille"], LILLE, LILLE_ORIGINS, "p2").place_id  # type: ignore[arg-type]
    reg.reject(["en mer"], "p1")
    return roubaix, lille


def _all_decisions(reg: PlaceRegistry) -> list[Decision]:
    return reg.all_decisions()


def _counts(reg: PlaceRegistry) -> tuple[int, int, int]:
    return len(reg.all_decisions()), len(reg.places()), len(reg.journal())


# --- export ----------------------------------------------------------------


def test_export_lists_places_and_writings_sorted(source: PlaceRegistry) -> None:
    roubaix, lille = _fill(source)
    data = export_registry(source)
    assert data["format"] == FORMAT == "prosopo-gw-atelier/lieux"
    assert data["version"] == 1
    assert data["exported_at"].endswith("+00:00")
    assert [p["place_id"] for p in data["places"]] == sorted([roubaix, lille])
    place = next(p for p in data["places"] if p["place_id"] == roubaix)
    assert place["fields"] == {
        "commune": {"value": "Roubaix", "origin": "rule"},
        "department": {"value": "59", "origin": "manual"},
        "insee_code": {"value": "59512", "origin": "rule"},
    }
    assert data["writings"] == [
        {"writing": "Lille", "status": "validated", "place_id": lille, "project": "p2"},
        {
            "writing": "ROUBAIX",
            "status": "validated",
            "place_id": roubaix,
            "project": "p1",
        },
        {
            "writing": "Roubaix, Nord",
            "status": "validated",
            "place_id": roubaix,
            "project": "p1",
        },
        {"writing": "en mer", "status": "rejected", "place_id": None, "project": "p1"},
    ]


def test_two_exports_differ_only_by_exported_at(source: PlaceRegistry) -> None:
    _fill(source)
    first, second = export_registry(source), export_registry(source)
    first.pop("exported_at")
    second.pop("exported_at")
    assert json.dumps(first) == json.dumps(second)


def test_export_is_json_serializable(source: PlaceRegistry) -> None:
    _fill(source)
    text = json.dumps(export_registry(source), ensure_ascii=False, indent=2)
    assert json.loads(text)["version"] == 1


# --- Step 1: round trip, conflicts, resolution ------------------------------


def test_round_trip_into_empty_registry(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    roubaix, lille = _fill(source)
    data = json.loads(json.dumps(export_registry(source)))
    assert import_registry(target, data).conflicts == []
    assert _all_decisions(target) == _all_decisions(source)
    for place_id in (roubaix, lille):
        assert target.place(place_id) == source.place(place_id)
    assert target.places() == source.places()
    entries = target.journal()
    assert [e.action for e in entries] == ["import"]
    assert entries[0].project is None
    again = export_registry(target)
    again.pop("exported_at")
    data.pop("exported_at")
    assert again == data


def test_import_is_one_undoable_entry(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    import_registry(target, export_registry(source))
    target.undo(target.journal()[0].entry_id)
    assert target.all_decisions() == []
    assert target.places() == []


def test_import_and_resolve_return_their_journal_entry(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    target.reject(["Lille"], "mine")
    data = export_registry(source)
    result = import_registry(target, data)
    assert result.entry_id == target.journal(limit=1)[0].entry_id
    [conflict] = result.conflicts
    entry = resolve_conflict(target, conflict, "incoming", "mine")
    assert entry == target.journal(limit=1)[0].entry_id
    assert resolve_conflict(target, conflict, "current", "mine") is None
    assert import_registry(target, data).entry_id is None


def test_writing_decided_between_plan_and_apply_is_a_conflict(
    tmp_path: Path,
    source: PlaceRegistry,
    target: PlaceRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another process decides a writing the import found absent."""
    _, lille = _fill(source)
    real_apply = target.apply_import
    calls = 0

    def other_process_decides_first(*args: Any, **kwargs: Any) -> int | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            with PlaceRegistry(tmp_path / "target.sqlite") as other:
                other.reject(["Lille"], "other-process")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(target, "apply_import", other_process_decides_first)
    result = import_registry(target, export_registry(source))
    [conflict] = result.conflicts
    assert conflict.writing == "Lille"
    assert conflict.current == Decision("Lille", None, "rejected", "other-process")
    assert conflict.incoming == source.decision("Lille")
    # Never overwritten in silence; the conflicting-only place is carried.
    assert target.decision("Lille") == conflict.current
    assert conflict.incoming_place == source.place(lille)
    with pytest.raises(KeyError):
        target.place(lille)
    assert target.decision("ROUBAIX") == source.decision("ROUBAIX")
    assert result.entry_id == target.journal(limit=1)[0].entry_id


def test_import_gives_up_if_the_registry_keeps_changing(
    source: PlaceRegistry, target: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fill(source)

    def always_outdated(*args: Any, **kwargs: Any) -> int | None:
        raise exchange._PlanOutdated

    monkeypatch.setattr(target, "apply_import", always_outdated)
    with pytest.raises(RuntimeError):
        import_registry(target, export_registry(source))
    assert target.all_decisions() == []


def test_reimport_same_data_writes_nothing(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    data = export_registry(source)
    import_registry(target, data)
    before = _counts(target)
    assert import_registry(target, data).conflicts == []
    assert _counts(target) == before


def test_same_decision_other_project_is_not_a_conflict(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    data = export_registry(source)
    for w in data["writings"]:
        w["project"] = "elsewhere"
    import_registry(target, export_registry(source))
    assert import_registry(target, data).conflicts == []
    assert target.decision("Lille") == source.decision("Lille")


def test_differing_decision_is_a_conflict_and_local_is_kept(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    roubaix, _ = _fill(source)
    local_lille = target.validate(
        ["Lille"], {"commune": "Lille-lez-Tours"}, {"commune": "manual"}, "mine"
    ).place_id
    target.validate(["en mer"], {"commune": "Mer"}, {"commune": "manual"}, "mine")
    conflicts = import_registry(target, export_registry(source)).conflicts
    by_writing = {c.writing: c for c in conflicts}
    assert sorted(by_writing) == ["Lille", "en mer"]
    lille = by_writing["Lille"]
    assert lille.current == Decision("Lille", local_lille, "validated", "mine")
    assert lille.incoming == source.decision("Lille")
    assert by_writing["en mer"].incoming == Decision("en mer", None, "rejected", "p1")
    # local values unchanged; non-conflicting writings applied
    assert target.decision("Lille") == lille.current
    assert target.decision("en mer") is not None
    assert target.decision("en mer").status == "validated"  # type: ignore[union-attr]
    assert target.decision("ROUBAIX") == source.decision("ROUBAIX")
    assert target.place(roubaix) == source.place(roubaix)
    assert target.journal()[0].action == "import"


def test_conflicting_only_place_is_not_created_but_carried(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _, lille = _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    with pytest.raises(KeyError):
        target.place(lille)
    assert conflict.incoming_place == source.place(lille)


def test_resolve_incoming_applies_and_creates_place(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _, lille = _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    entries = len(target.journal())
    resolve_conflict(target, conflict, "incoming", "proj")
    assert target.decision("Lille") == Decision("Lille", lille, "validated", "proj")
    assert target.place(lille) == source.place(lille)
    assert len(target.journal()) == entries + 1
    target.undo(target.journal()[0].entry_id)
    assert target.decision("Lille") == Decision("Lille", None, "rejected", "mine")
    with pytest.raises(KeyError):
        target.place(lille)


def test_resolve_incoming_rejection(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    target.validate(["en mer"], {"commune": "Mer"}, {"commune": "manual"}, "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    resolve_conflict(target, conflict, "incoming", None)
    assert target.decision("en mer") == Decision("en mer", None, "rejected", None)


def test_resolve_current_changes_nothing(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    before = _counts(target)
    resolve_conflict(target, conflict, "current", "proj")
    assert _counts(target) == before
    assert target.decision("Lille") == conflict.current


def test_resolve_with_brief_signature_and_existing_place(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    roubaix, _ = _fill(source)
    import_registry(target, export_registry(source))
    target.reject(["ROUBAIX"], "mine")
    conflict = Conflict(
        "ROUBAIX",
        current=target.decision("ROUBAIX"),  # type: ignore[arg-type]
        incoming=Decision("ROUBAIX", roubaix, "validated", "p1"),
    )
    resolve_conflict(target, conflict, "incoming", "proj")
    assert target.decision("ROUBAIX") == Decision(
        "ROUBAIX", roubaix, "validated", "proj"
    )


def test_resolve_unknown_place_without_data_raises(target: PlaceRegistry) -> None:
    conflict = Conflict(
        "X",
        current=Decision("X", None, "rejected", None),
        incoming=Decision("X", "missing-id", "validated", None),
    )
    with pytest.raises(KeyError):
        resolve_conflict(target, conflict, "incoming", "proj")
    assert target.decision("X") is None


def test_resolve_rejects_bad_keep(target: PlaceRegistry) -> None:
    conflict = Conflict(
        "X",
        current=Decision("X", None, "rejected", None),
        incoming=Decision("X", None, "rejected", "p"),
    )
    with pytest.raises(ValueError):
        resolve_conflict(target, conflict, "both", None)  # type: ignore[arg-type]


def test_existing_place_keeps_local_fields(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    roubaix, _ = _fill(source)
    import_registry(target, export_registry(source))
    target.correct(roubaix, "commune", "Roubaix (Nord)", "mine")
    local = target.place(roubaix)
    source.validate(["Roubaix 59"], {}, {}, "p3", place_id=roubaix)
    assert import_registry(target, export_registry(source)).conflicts == []
    assert target.place(roubaix) == local
    assert target.decision("Roubaix 59") == source.decision("Roubaix 59")


def test_writing_may_point_to_a_local_place(target: PlaceRegistry) -> None:
    local = target.validate(["Lille"], LILLE, LILLE_ORIGINS, "mine").place_id  # type: ignore[arg-type]
    data = {
        "format": FORMAT,
        "version": 1,
        "exported_at": "2026-11-07T00:00:00+00:00",
        "places": [],
        "writings": [
            {
                "writing": "LILLE",
                "status": "validated",
                "place_id": local,
                "project": None,
            }
        ],
    }
    assert import_registry(target, data).conflicts == []
    assert target.decision("LILLE") == Decision("LILLE", local, "validated", None)


def test_unreferenced_incoming_place_is_created(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    roubaix, _ = _fill(source)
    source.detach(["ROUBAIX", "Roubaix, Nord"], "p1")
    import_registry(target, export_registry(source))
    assert target.place(roubaix) == source.place(roubaix)


# --- Step 2: validation before writing ---------------------------------------


def _valid(source: PlaceRegistry) -> dict[str, Any]:
    _fill(source)
    return export_registry(source)


def _mutations() -> list[tuple[str, Any]]:
    def setter(path: tuple[Any, ...], value: Any) -> Any:
        def apply(d: dict[str, Any]) -> None:
            node: Any = d
            for step in path[:-1]:
                node = node[step]
            node[path[-1]] = value

        return apply

    def deleter(path: tuple[Any, ...]) -> Any:
        def apply(d: dict[str, Any]) -> None:
            node: Any = d
            for step in path[:-1]:
                node = node[step]
            del node[path[-1]]

        return apply

    def dup_writing(d: dict[str, Any]) -> None:
        d["writings"].append(dict(d["writings"][0]))

    def dup_place(d: dict[str, Any]) -> None:
        d["places"].append(copy.deepcopy(d["places"][0]))

    return [
        ("other format", setter(("format",), "prosopo-gw/other")),
        ("version 2", setter(("version",), 2)),
        ("version as string", setter(("version",), "1")),
        ("version as bool", setter(("version",), True)),
        ("missing format", deleter(("format",))),
        ("missing version", deleter(("version",))),
        ("missing places", deleter(("places",))),
        ("missing writings", deleter(("writings",))),
        ("exported_at not str", setter(("exported_at",), 3)),
        ("places not list", setter(("places",), {})),
        ("place not object", setter(("places", 0), "x")),
        ("place without id", deleter(("places", 0, "place_id"))),
        ("place id empty", setter(("places", 0, "place_id"), "")),
        ("fields not object", setter(("places", 0, "fields"), [])),
        ("unknown kind", setter(("places", 0, "fields", "street"), {})),
        ("field not object", setter(("places", 0, "fields", "commune"), "Lille")),
        ("field without origin", deleter(("places", 0, "fields", "commune", "origin"))),
        ("unknown origin", setter(("places", 0, "fields", "commune", "origin"), "ai")),
        ("value not str", setter(("places", 0, "fields", "commune", "value"), 59)),
        ("duplicate place", dup_place),
        ("writings not list", setter(("writings",), None)),
        ("writing not object", setter(("writings", 0), 1)),
        ("writing missing", deleter(("writings", 0, "writing"))),
        ("writing empty", setter(("writings", 0, "writing"), "")),
        ("unknown status", setter(("writings", 0, "status"), "maybe")),
        ("missing project", deleter(("writings", 0, "project"))),
        ("project not str", setter(("writings", 0, "project"), 1)),
        ("place_id not str", setter(("writings", 0, "place_id"), 5)),
        ("validated without place", setter(("writings", 0, "place_id"), None)),
        ("rejected with place", setter(("writings", 0, "status"), "rejected")),
        ("unknown place", setter(("writings", 0, "place_id"), "nowhere")),
        ("duplicate writing", dup_writing),
    ]


@pytest.mark.parametrize(
    "mutate", [m for _, m in _mutations()], ids=[n for n, _ in _mutations()]
)
def test_invalid_document_writes_nothing(
    source: PlaceRegistry, target: PlaceRegistry, mutate: Any
) -> None:
    data = _valid(source)
    # a populated target: errors must not be checked row by row while writing
    target.validate(["Ailleurs"], {"commune": "Ailleurs"}, {"commune": "manual"}, "m")
    mutate(data)
    before = _counts(target)
    with pytest.raises(RegistryFormatError):
        import_registry(target, data)
    assert _counts(target) == before


def test_document_not_a_mapping(target: PlaceRegistry) -> None:
    with pytest.raises(RegistryFormatError, match="object"):
        import_registry(target, [])


def test_format_error_message_is_clear(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    data = _valid(source)
    data["version"] = 2
    with pytest.raises(RegistryFormatError, match="version 2"):
        import_registry(target, data)
    data["version"] = 1
    data["format"] = "other"
    with pytest.raises(RegistryFormatError, match="prosopo-gw-atelier/lieux"):
        import_registry(target, data)


def test_registry_format_error_is_a_value_error() -> None:
    assert issubclass(RegistryFormatError, ValueError)


def test_place_dataclass_roundtrip_fields(source: PlaceRegistry) -> None:
    roubaix, _ = _fill(source)
    assert source.place(roubaix) == Place(roubaix, ROUBAIX, ROUBAIX_ORIGINS)  # type: ignore[arg-type]


# --- Fix round 1: ill-typed enum values, stale conflicts ----------------------


def _set_kind_key(key: Any) -> Any:
    def apply(d: dict[str, Any]) -> None:
        fields = d["places"][0]["fields"]
        fields[key] = fields.pop("commune")

    return apply


def _set_at(path: tuple[Any, ...], value: Any) -> Any:
    def apply(d: dict[str, Any]) -> None:
        node: Any = d
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = value

    return apply


_STATUS = ("writings", 0, "status")
_ORIGIN = ("places", 0, "fields", "commune", "origin")
_ENUM_CASES = {
    "status-list": _set_at(_STATUS, []),
    "status-dict": _set_at(_STATUS, {}),
    "origin-list": _set_at(_ORIGIN, []),
    "origin-dict": _set_at(_ORIGIN, {}),
    "format-list": _set_at(("format",), []),
    "format-dict": _set_at(("format",), {}),
    # JSON object keys are always strings (an unhashable kind cannot even be
    # a key); a hand-built mapping may still carry non-string keys.
    "kind-int": _set_kind_key(3),
    "kind-tuple": _set_kind_key(("commune",)),
}


@pytest.mark.parametrize("mutate", list(_ENUM_CASES.values()), ids=list(_ENUM_CASES))
def test_unhashable_or_non_str_enum_values_are_format_errors(
    source: PlaceRegistry, target: PlaceRegistry, mutate: Any
) -> None:
    data = _valid(source)
    target.validate(["Ailleurs"], {"commune": "Ailleurs"}, {"commune": "manual"}, "m")
    mutate(data)
    before = _counts(target)
    with pytest.raises(RegistryFormatError):
        import_registry(target, data)
    assert _counts(target) == before


def test_resolve_stale_conflict_raises_and_writes_nothing(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _, lille = _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    other = target.validate(
        ["Lille"], {"commune": "Lille"}, {"commune": "manual"}, "m"
    ).place_id
    local = target.decision("Lille")
    before = _counts(target)
    with pytest.raises(StaleConflictError, match="Lille"):
        resolve_conflict(target, conflict, "incoming", "proj")
    assert issubclass(StaleConflictError, ValueError)
    assert (
        target.decision("Lille") == local == Decision("Lille", other, "validated", "m")
    )
    assert _counts(target) == before
    with pytest.raises(KeyError):
        target.place(lille)


def test_resolve_after_local_detach_is_stale(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    target.detach(["Lille"], "mine")
    before = _counts(target)
    with pytest.raises(StaleConflictError):
        resolve_conflict(target, conflict, "incoming", "proj")
    assert _counts(target) == before
    assert target.decision("Lille") is None


def test_resolve_ignores_a_project_only_change(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _, lille = _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    target.reject(["Lille"], "other project")
    resolve_conflict(target, conflict, "incoming", "proj")
    assert target.decision("Lille") == Decision("Lille", lille, "validated", "proj")


def test_resolve_uses_a_place_that_appeared_meanwhile(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _, lille = _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    target.apply_import(
        [RowChange("places", {"place_id": lille}, {"created_at": "t"})], None
    )
    resolve_conflict(target, conflict, "incoming", "proj")
    assert target.decision("Lille") == Decision("Lille", lille, "validated", "proj")
    assert target.place(lille).fields == {}  # existing place left as it was


def test_resolve_race_on_incoming_place_is_stale(
    source: PlaceRegistry, target: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, lille = _fill(source)
    target.reject(["Lille"], "mine")
    [conflict] = import_registry(target, export_registry(source)).conflicts
    original = target.apply_import

    def racing(*args: Any, **kwargs: Any) -> int | None:
        # another writer creates the place between the reads and the transaction
        monkeypatch.setattr(target, "apply_import", original)
        original([RowChange("places", {"place_id": lille}, {"created_at": "t"})], None)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, "apply_import", racing)
    with pytest.raises(StaleConflictError, match="place"):
        resolve_conflict(target, conflict, "incoming", "proj")
    assert target.decision("Lille") == conflict.current
    assert target.place(lille).fields == {}
