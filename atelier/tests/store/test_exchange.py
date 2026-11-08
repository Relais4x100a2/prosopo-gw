import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from prosopo_gw_atelier.places.levels import Level
from prosopo_gw_atelier.refdata import RefData, load_refdata
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

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "refdata_mini"
ROUBAIX = (
    Level(0, "Roubaix", type="commune", identifier="59512", origin="rule"),
    Level(1, "Nord", type="departement", identifier="59", origin="manual"),
)
LILLE = (Level(0, "Lille", type="commune", identifier="59350", origin="insee"),)
MARCONNE = (
    Level(0, "Les Fontaines", type="lieu_dit", origin="written"),
    Level(1, "Marconne", type="commune", identifier="62551", origin="insee"),
    Level(2, "Pas-de-Calais", type="departement", identifier="62", origin="insee"),
    Level(3, "Hauts-de-France", type="region", origin="insee"),
    Level(4, "France", type="pays", origin="insee"),
)


def _commune(name: str) -> tuple[Level, ...]:
    return (Level(0, name, type="commune", origin="manual"),)


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(MINI)


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
        ["ROUBAIX", "Roubaix, Nord"], ROUBAIX, "59100", "written", "p1"
    ).place_id
    lille = reg.validate(["Lille"], LILLE, None, None, "p2").place_id
    reg.reject(["en mer"], "p1")
    return roubaix, lille


def _all_decisions(reg: PlaceRegistry) -> list[Decision]:
    return reg.all_decisions()


def _counts(reg: PlaceRegistry) -> tuple[int, int, int, int, int]:
    places = reg.places()
    return (
        len(reg.all_decisions()),
        len(places),
        len(reg.journal()),
        sum(len(p.levels) for p in places),
        sum(p.postal_code is not None for p in places),
    )


# --- export ----------------------------------------------------------------


def test_export_lists_places_and_writings_sorted(source: PlaceRegistry) -> None:
    roubaix, lille = _fill(source)
    data = export_registry(source)
    assert data["format"] == FORMAT == "prosopo-gw-atelier/lieux"
    assert data["version"] == 2
    assert data["exported_at"].endswith("+00:00")
    assert [p["place_id"] for p in data["places"]] == sorted([roubaix, lille])
    place = next(p for p in data["places"] if p["place_id"] == roubaix)
    assert place["postal_code"] == {"value": "59100", "origin": "written"}
    assert [
        (lv["rank"], lv["name"], lv["type"], lv["origin"]) for lv in place["levels"]
    ] == [
        (0, "Roubaix", "commune", "rule"),
        (1, "Nord", "departement", "manual"),
    ]
    other = next(p for p in data["places"] if p["place_id"] == lille)
    assert other["postal_code"] is None
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
    assert json.loads(text)["version"] == 2


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
        ["Lille"], _commune("Lille-lez-Tours"), None, None, "mine"
    ).place_id
    target.validate(["en mer"], _commune("Mer"), None, None, "mine")
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
    target.validate(["en mer"], _commune("Mer"), None, None, "mine")
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


def test_existing_place_keeps_local_levels(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    roubaix, _ = _fill(source)
    import_registry(target, export_registry(source))
    target.set_levels(roubaix, _commune("Roubaix (Nord)"), "59100", "manual", "mine")
    local = target.place(roubaix)
    source.validate(["Roubaix 59"], ROUBAIX, None, None, "p3", place_id=roubaix)
    assert import_registry(target, export_registry(source)).conflicts == []
    assert target.place(roubaix) == local
    assert target.decision("Roubaix 59") == source.decision("Roubaix 59")


def test_writing_may_point_to_a_local_place(target: PlaceRegistry) -> None:
    local = target.validate(["Lille"], LILLE, None, None, "mine").place_id
    data = {
        "format": FORMAT,
        "version": 2,
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
        ("version 3", setter(("version",), 3)),
        ("version 0", setter(("version",), 0)),
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
        ("missing levels", deleter(("places", 0, "levels"))),
        ("levels not list", setter(("places", 0, "levels"), {})),
        ("level not object", setter(("places", 0, "levels", 0), "Lille")),
        ("level without origin", deleter(("places", 0, "levels", 0, "origin"))),
        ("unknown origin", setter(("places", 0, "levels", 0, "origin"), "ai")),
        ("level without status", deleter(("places", 0, "levels", 0, "status"))),
        ("unknown status", setter(("places", 0, "levels", 0, "status"), "maybe")),
        ("unknown nature", setter(("places", 0, "levels", 0, "nature"), "annexee")),
        ("bad type slug", setter(("places", 0, "levels", 0, "type"), "Commune!")),
        ("level without name", deleter(("places", 0, "levels", 0, "name"))),
        ("level name empty", setter(("places", 0, "levels", 0, "name"), " ")),
        ("name not str", setter(("places", 0, "levels", 0, "name"), 59)),
        ("rank as string", setter(("places", 0, "levels", 0, "rank"), "0")),
        ("rank as bool", setter(("places", 0, "levels", 0, "rank"), False)),
        ("rank gap", setter(("places", 0, "levels", 0, "rank"), 2)),
        ("latitude not number", setter(("places", 0, "levels", 0, "latitude"), "n")),
        ("latitude out of range", setter(("places", 0, "levels", 0, "latitude"), 91)),
        ("postal not object", setter(("places", 0, "postal_code"), "59000")),
        ("postal without origin", setter(("places", 0, "postal_code"), {"value": "1"})),
        (
            "postal llm origin",
            setter(("places", 0, "postal_code"), {"value": "1", "origin": "llm"}),
        ),
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
    target.validate(["Ailleurs"], _commune("Ailleurs"), None, None, "m")
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
    data["version"] = 3
    with pytest.raises(RegistryFormatError, match="version 3"):
        import_registry(target, data)
    data["version"] = 2
    data["format"] = "other"
    with pytest.raises(RegistryFormatError, match="prosopo-gw-atelier/lieux"):
        import_registry(target, data)


def test_registry_format_error_is_a_value_error() -> None:
    assert issubclass(RegistryFormatError, ValueError)


def test_place_dataclass_roundtrip_levels(source: PlaceRegistry) -> None:
    roubaix, _ = _fill(source)
    assert source.place(roubaix) == Place(roubaix, ROUBAIX, "59100", "written")


# --- Fix round 1: ill-typed enum values, stale conflicts ----------------------


def _set_at(path: tuple[Any, ...], value: Any) -> Any:
    def apply(d: dict[str, Any]) -> None:
        node: Any = d
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = value

    return apply


_STATUS = ("writings", 0, "status")
_ORIGIN = ("places", 0, "levels", 0, "origin")
_ENUM_CASES = {
    "status-list": _set_at(_STATUS, []),
    "status-dict": _set_at(_STATUS, {}),
    "origin-list": _set_at(_ORIGIN, []),
    "origin-dict": _set_at(_ORIGIN, {}),
    "format-list": _set_at(("format",), []),
    "format-dict": _set_at(("format",), {}),
    "nature-list": _set_at(("places", 0, "levels", 0, "nature"), []),
    "type-list": _set_at(("places", 0, "levels", 0, "type"), []),
}


@pytest.mark.parametrize("mutate", list(_ENUM_CASES.values()), ids=list(_ENUM_CASES))
def test_unhashable_or_non_str_enum_values_are_format_errors(
    source: PlaceRegistry, target: PlaceRegistry, mutate: Any
) -> None:
    data = _valid(source)
    target.validate(["Ailleurs"], _commune("Ailleurs"), None, None, "m")
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
    other = target.validate(["Lille"], _commune("Lille"), None, None, "m").place_id
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
    assert target.place(lille).levels == ()  # existing place left as it was


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
    assert target.place(lille).levels == ()


# --- version 2: levels, proposals, version 1 documents -----------------------


def test_export_is_version_2_with_levels(source: PlaceRegistry) -> None:
    marconne = source.validate(["Marconne"], MARCONNE, "62140", "rule", "p1").place_id
    data = export_registry(source)
    assert data["version"] == 2
    [place] = data["places"]
    assert place["place_id"] == marconne
    assert [lv["rank"] for lv in place["levels"]] == [0, 1, 2, 3, 4]
    assert [lv["name"] for lv in place["levels"]] == [lv.name for lv in MARCONNE]
    assert place["levels"][1] == {
        "rank": 1,
        "name": "Marconne",
        "written": None,
        "type": "commune",
        "identifier": "62551",
        "source": None,
        "start": None,
        "end": None,
        "latitude": None,
        "longitude": None,
        "nature": None,
        "origin": "insee",
        "status": "validated",
    }


def test_round_trip_keeps_levels_and_proposals(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    chain = (
        Level(0, "Lomme", type="commune_historique", identifier="59355",
              source="COG 2026", end="2000-01-01", nature="associee",
              origin="insee", status="proposed"),
        Level(1, "Lille", written="Lille-Lomme", type="commune",
              identifier="59350", latitude=50.63, longitude=3.06, origin="insee"),
        Level(2, "Nord", type="departement", identifier="59", origin="manual"),
    )  # fmt: skip
    place_id = source.validate(["Lille"], chain, "59000", "insee", "p1").place_id
    data = json.loads(json.dumps(export_registry(source)))
    assert import_registry(target, data).conflicts == []
    assert target.place(place_id).levels == chain
    assert target.place(place_id) == source.place(place_id)
    assert target.place(place_id).levels[0].status == "proposed"


def _v1_document(
    places: list[dict[str, Any]], writings: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": 1,
        "exported_at": "2026-11-07T00:00:00+00:00",
        "places": places,
        "writings": writings,
    }


def _v1_field(value: str, origin: str) -> dict[str, str]:
    return {"value": value, "origin": origin}


def _v1_lille() -> dict[str, Any]:
    return {
        "place_id": "p-lille",
        "fields": {
            "commune": _v1_field("Lille", "reference"),
            "insee_code": _v1_field("59350", "reference"),
            "department": _v1_field("59", "reference"),
            "country": _v1_field("France", "rule"),
            "former_name": _v1_field("Lomme", "rule"),
            "postal_code": _v1_field("59000", "rule"),
        },
    }


def _writing(
    text: str, place_id: str | None, status: str = "validated"
) -> dict[str, Any]:
    return {"writing": text, "status": status, "place_id": place_id, "project": "p1"}


def test_import_v1_document(target: PlaceRegistry, ref: RefData) -> None:
    target.reject(["Lomme"], "mine")
    data = _v1_document(
        [_v1_lille()],
        [_writing("Lille", "p-lille"), _writing("Lomme", "p-lille")],
    )
    result = import_registry(target, data, ref)
    assert [c.writing for c in result.conflicts] == ["Lomme"]  # as in version 1
    assert target.decision("Lomme") == Decision("Lomme", None, "rejected", "mine")
    assert target.decision("Lille") == Decision("Lille", "p-lille", "validated", "p1")
    place = target.place("p-lille")
    assert [(lv.rank, lv.name, lv.status) for lv in place.levels] == [
        (0, "Lomme", "proposed"),
        (1, "Lille", "validated"),
        (2, "Nord", "validated"),
        (3, "France", "validated"),
    ]
    assert place.levels[0].type == "commune_historique"
    assert (place.postal_code, place.postal_origin) == ("59000", "rule")


def test_import_v1_document_without_refdata(target: PlaceRegistry) -> None:
    data = _v1_document([_v1_lille()], [_writing("Lille", "p-lille")])
    assert import_registry(target, data).conflicts == []
    place = target.place("p-lille")
    assert [(lv.name, lv.type, lv.status) for lv in place.levels] == [
        ("Lomme", None, "proposed"),
        ("Lille", "commune", "validated"),
        ("59", "departement", "validated"),
        ("France", "pays", "validated"),
    ]


def test_import_v1_place_without_level_is_named_after_its_first_writing(
    target: PlaceRegistry,
) -> None:
    data = _v1_document(
        [{"place_id": "p-x", "fields": {}}, {"place_id": "p-y", "fields": {}}],
        [
            _writing("Zeta", "p-x"),
            _writing("Alpha", "p-x"),
            _writing("Beta", None, "rejected"),
        ],
    )
    import_registry(target, data)
    assert target.place("p-x").levels == (Level(0, "Alpha", origin="written"),)
    assert target.place("p-y").levels == ()


def test_import_v1_conversion_error_writes_nothing(
    target: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Origine manquante pour le champ commune.")

    monkeypatch.setattr(exchange, "levels_from_v1", refuse)
    data = _v1_document([_v1_lille()], [_writing("Lille", "p-lille")])
    with pytest.raises(RegistryFormatError, match="p-lille"):
        import_registry(target, data)
    assert _counts(target) == (0, 0, 0, 0, 0)


@pytest.mark.parametrize("kind", [3, ("commune",)])
def test_import_v1_non_string_kind_is_a_format_error(
    target: PlaceRegistry, kind: Any
) -> None:
    place = _v1_lille()
    place["fields"][kind] = place["fields"].pop("commune")
    with pytest.raises(RegistryFormatError):
        import_registry(target, _v1_document([place], []))
    assert _counts(target) == (0, 0, 0, 0, 0)


def test_invalid_level_rejected(source: PlaceRegistry, target: PlaceRegistry) -> None:
    source.validate(["Marconne"], MARCONNE, None, None, "p1")
    data = export_registry(source)
    del data["places"][0]["levels"][2]["name"]
    with pytest.raises(RegistryFormatError, match="name"):
        import_registry(target, data)
    assert _counts(target) == (0, 0, 0, 0, 0)


def test_invalid_chain_error_names_the_place_in_french(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    place_id = source.validate(["Marconne"], MARCONNE, None, None, "p1").place_id
    data = export_registry(source)
    data["places"][0]["levels"][3]["rank"] = 7
    with pytest.raises(RegistryFormatError, match=place_id) as caught:
        import_registry(target, data)
    assert "Rang 7" in str(caught.value)
    assert _counts(target) == (0, 0, 0, 0, 0)


def _v1_mutations() -> dict[str, Any]:
    def change(mutate: Any) -> Any:
        def apply(place: dict[str, Any]) -> None:
            mutate(place)

        return apply

    def set_field(name: str, value: Any) -> Any:
        return change(lambda p: p["fields"].__setitem__(name, value))

    return {
        "fields not object": change(lambda p: p.__setitem__("fields", [])),
        "unknown kind": set_field("street", _v1_field("x", "rule")),
        "field not object": set_field("commune", "Lille"),
        "field without origin": change(lambda p: p["fields"]["commune"].pop("origin")),
        "unknown origin": set_field("commune", _v1_field("Lille", "ai")),
        "origin list": set_field("commune", _v1_field("Lille", [])),
        "value not str": set_field("commune", {"value": 59, "origin": "rule"}),
        "place_id list": change(lambda p: p.__setitem__("place_id", [])),
        "place_id object": change(lambda p: p.__setitem__("place_id", {"a": 1})),
        "place_id empty": change(lambda p: p.__setitem__("place_id", "")),
    }


@pytest.mark.parametrize(
    "mutate", list(_v1_mutations().values()), ids=list(_v1_mutations())
)
def test_invalid_v1_place_writes_nothing(target: PlaceRegistry, mutate: Any) -> None:
    place = _v1_lille()
    mutate(place)
    data = _v1_document([place], [_writing("Lille", "p-lille")])
    with pytest.raises(RegistryFormatError):
        import_registry(target, data)
    assert _counts(target) == (0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda lv: lv.__setitem__("rank", "0"),
        lambda lv: lv.pop("name"),
        lambda lv: lv.__setitem__("origin", "ai"),
        lambda lv: lv.__setitem__("latitude", "n"),
    ],
    ids=["rank as string", "level without name", "unknown origin", "bad latitude"],
)
def test_level_errors_name_the_place(
    source: PlaceRegistry, target: PlaceRegistry, mutate: Any
) -> None:
    place_id = source.validate(["Marconne"], MARCONNE, None, None, "p1").place_id
    data = export_registry(source)
    mutate(data["places"][0]["levels"][1])
    with pytest.raises(RegistryFormatError, match=place_id) as caught:
        import_registry(target, data)
    assert "lieu" in str(caught.value)
    assert _counts(target) == (0, 0, 0, 0, 0)


# --- arrondissement precisions --------------------------------------------------


def _decide(reg: PlaceRegistry) -> None:
    reg.decide_precision(
        "Paris 7e", "rue de Grenelle", "paris-1860", "75107", None, "p"
    )
    reg.decide_precision("Paris", None, "", None, None, "p")
    reg.decide_precision(
        "Paris", "rue de Rivoli", "paris-1795", "paris-1795-04", "q1", "p"
    )


def test_export_precisions(source: PlaceRegistry) -> None:
    _decide(source)
    data = export_registry(source)
    assert data["version"] == 2
    assert data["precisions"] == [
        {
            "ecriture": "Paris",
            "complement": "",
            "periode": "",
            "arrondissement_id": None,
            "quartier_id": None,
        },
        {
            "ecriture": "Paris",
            "complement": "rue de Rivoli",
            "periode": "paris-1795",
            "arrondissement_id": "paris-1795-04",
            "quartier_id": "q1",
        },
        {
            "ecriture": "Paris 7e",
            "complement": "rue de Grenelle",
            "periode": "paris-1860",
            "arrondissement_id": "75107",
            "quartier_id": None,
        },
    ]


def test_export_import_precisions(source: PlaceRegistry, target: PlaceRegistry) -> None:
    _fill(source)
    _decide(source)
    data = json.loads(json.dumps(export_registry(source)))
    assert import_registry(target, data).conflicts == []
    ids = {
        key: (d.arrondissement_id, d.quartier_id)
        for key, d in target.precision_decisions().items()
    }
    assert ids == {
        key: (d.arrondissement_id, d.quartier_id)
        for key, d in source.precision_decisions().items()
    }
    assert len(ids) == 3
    entries = target.journal()
    assert [e.action for e in entries] == ["import"]
    # one undoable entry
    target.undo(entries[0].entry_id)
    assert target.precision_decisions() == {}
    # reimport of the same document writes nothing
    import_registry(target, data)
    n = len(target.journal())
    assert import_registry(target, data).entry_id is None
    assert len(target.journal()) == n


def test_import_keeps_local_precision(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    source.decide_precision("Paris", None, "paris-1860", "75107", None, "p")
    target.decide_precision("Paris", None, "paris-1860", "75108", None, "p")
    source.decide_precision("Paris", None, "", "paris-07", None, "p")
    target.decide_precision("Paris", None, "", "paris-07", None, "p")
    source.decide_precision("Lyon", None, "", "69381", None, "p")
    result = import_registry(target, export_registry(source))
    assert (
        target.precision_decisions()[("Paris", "", "paris-1860")].arrondissement_id
        == "75108"
    )
    assert result.precisions_kept_local == (("Paris", "", "paris-1860"),)
    entry = next(e for e in target.journal() if e.action == "import")
    assert entry.payload["details"]["precisions_kept_local"] == [
        ["Paris", "", "paris-1860"]
    ]
    assert ("Lyon", "", "") in target.precision_decisions()


def test_import_without_precisions_key(
    source: PlaceRegistry, target: PlaceRegistry
) -> None:
    _fill(source)
    data = export_registry(source)
    del data["precisions"]
    assert import_registry(target, data).conflicts == []
    assert target.precision_decisions() == {}


def test_import_normalises_empty_arrondissement_id(target: PlaceRegistry) -> None:
    data = {
        "format": FORMAT,
        "version": 2,
        "exported_at": "x",
        "places": [],
        "writings": [],
        "precisions": [
            {
                "ecriture": "Paris",
                "complement": "",
                "periode": "paris-1795",
                "arrondissement_id": "",
                "quartier_id": None,
            }
        ],
    }
    import_registry(target, data)
    [d] = target.precision_decisions().values()
    assert (d.arrondissement_id, d.quartier_id) == (None, None)


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        {
            "complement": "",
            "periode": "",
            "arrondissement_id": None,
            "quartier_id": None,
        },
        {
            "ecriture": "",
            "complement": "",
            "periode": "",
            "arrondissement_id": None,
            "quartier_id": None,
        },
        {
            "ecriture": "P",
            "complement": 3,
            "periode": "",
            "arrondissement_id": None,
            "quartier_id": None,
        },
        {
            "ecriture": "P",
            "complement": "",
            "periode": None,
            "arrondissement_id": None,
            "quartier_id": None,
        },
        {
            "ecriture": "P",
            "complement": "",
            "periode": "",
            "arrondissement_id": 7,
            "quartier_id": None,
        },
    ],
)
def test_invalid_precision_is_a_format_error(target: PlaceRegistry, bad: Any) -> None:
    data = {
        "format": FORMAT,
        "version": 2,
        "exported_at": "x",
        "places": [],
        "writings": [],
        "precisions": [bad],
    }
    with pytest.raises(RegistryFormatError):
        import_registry(target, data)
    assert target.precision_decisions() == {}


def test_duplicate_precision_is_a_format_error(target: PlaceRegistry) -> None:
    row = {
        "ecriture": "P",
        "complement": "",
        "periode": "",
        "arrondissement_id": None,
        "quartier_id": None,
    }
    data = {
        "format": FORMAT,
        "version": 2,
        "exported_at": "x",
        "places": [],
        "writings": [],
        "precisions": [row, dict(row)],
    }
    with pytest.raises(RegistryFormatError, match="duplicate"):
        import_registry(target, data)
