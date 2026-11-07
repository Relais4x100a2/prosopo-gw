"""Export and import of the personal place registry (design § 6.3 "Partage").

Format (readable JSON, sorted so that two exports of the same registry differ
only by ``exported_at`` and diff cleanly under version control)::

    {
      "format": "prosopo-gw-atelier/lieux",
      "version": 1,
      "exported_at": "2026-11-07T10:00:00+00:00",
      "places": [
        {"place_id": "<uuid>",
         "fields": {"commune": {"value": "Roubaix", "origin": "rule"}, …}}
      ],
      "writings": [
        {"writing": "ROUBAIX", "status": "validated",
         "place_id": "<uuid>", "project": "p1"},
        {"writing": "en mer", "status": "rejected",
         "place_id": null, "project": "p1"}
      ]
    }

Places are sorted by ``place_id``, their fields by kind, writings by text.
Creation and decision timestamps are not exported (imported rows get the
import time).

Import
    The whole document is validated first (:class:`RegistryFormatError`,
    nothing written). Then, per writing: absent locally → applied; same status
    and same ``place_id`` → nothing to do (the project does not matter);
    otherwise → a :class:`Conflict`, the local decision is left unchanged.
    A place whose id is unknown locally is created with its fields and
    origins, unless only conflicting writings need it: it then travels in
    ``Conflict.incoming_place`` and is created only if the conflict is
    resolved with the incoming decision. A place whose id is already known
    keeps its local fields; differing fields are neither overwritten nor
    reported (only writings conflict). Everything applied goes into one
    undoable ``import`` journal entry; nothing is journaled if nothing changes.
    "Absent locally" is checked again inside the write transaction: a writing
    another process decided in the meantime becomes a conflict too.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast, get_args

from ..places.model import ElementKind
from .registry import Decision, Origin, Place, PlaceRegistry, RowChange, Status

FORMAT = "prosopo-gw-atelier/lieux"
VERSION = 1

_KINDS = frozenset(get_args(ElementKind))
_ORIGINS = frozenset(get_args(Origin))
_STATUSES = frozenset(get_args(Status))


class RegistryFormatError(ValueError):
    """The document is not a valid registry export; nothing was written."""


class StaleConflictError(ValueError):
    """The local decision changed since the conflict was reported."""


@dataclass(frozen=True)
class Conflict:
    """A writing decided differently here and in the imported document.

    ``incoming_place`` is the imported place ``incoming`` points to, when the
    document carries it, so that resolving with the incoming decision can
    create it if it is not in the registry.
    """

    writing: str
    current: Decision
    incoming: Decision
    incoming_place: Place | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def export_registry(registry: PlaceRegistry) -> dict[str, Any]:
    """The whole registry as a JSON-serializable document."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": _now(),
        "places": [
            {
                "place_id": place.place_id,
                "fields": {
                    kind: {"value": place.fields[kind], "origin": place.origins[kind]}
                    for kind in sorted(place.fields)
                },
            }
            for place in registry.places()
        ],
        "writings": [
            {
                "writing": d.writing,
                "status": d.status,
                "place_id": d.place_id,
                "project": d.project,
            }
            for d in registry.all_decisions()
        ],
    }


# -- validation -----------------------------------------------------------


def _fail(message: str) -> RegistryFormatError:
    return RegistryFormatError(f"invalid registry export: {message}")


def _get(obj: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in obj:
        raise _fail(f"{where}: missing key {key!r}")
    return obj[key]


def _text(value: Any, where: str, *, optional: bool = False) -> Any:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        kind = "a non-empty string or null" if optional else "a non-empty string"
        raise _fail(f"{where} must be {kind}, not {value!r}")
    return value


def _parse_place(index: int, raw: Any) -> Place:
    where = f"places[{index}]"
    if not isinstance(raw, Mapping):
        raise _fail(f"{where} must be an object")
    place_id = _text(_get(raw, "place_id", where), f"{where}.place_id")
    raw_fields = _get(raw, "fields", where)
    if not isinstance(raw_fields, Mapping):
        raise _fail(f"{where}.fields must be an object")
    fields: dict[ElementKind, str] = {}
    origins: dict[ElementKind, Origin] = {}
    for kind, field in raw_fields.items():
        at = f"{where}.fields.{kind}"
        if not isinstance(kind, str) or kind not in _KINDS:
            raise _fail(
                f"{at}: unknown element kind (expected one of {sorted(_KINDS)})"
            )
        if not isinstance(field, Mapping):
            raise _fail(f"{at} must be an object with 'value' and 'origin'")
        value = _get(field, "value", at)
        if not isinstance(value, str):
            raise _fail(f"{at}.value must be a string, not {value!r}")
        origin = _get(field, "origin", at)
        if not isinstance(origin, str) or origin not in _ORIGINS:
            raise _fail(
                f"{at}.origin: unknown origin {origin!r} "
                f"(expected one of {sorted(_ORIGINS)})"
            )
        fields[cast(ElementKind, kind)] = value
        origins[cast(ElementKind, kind)] = cast(Origin, origin)
    return Place(place_id, fields, origins)


def _parse_writing(index: int, raw: Any) -> Decision:
    where = f"writings[{index}]"
    if not isinstance(raw, Mapping):
        raise _fail(f"{where} must be an object")
    writing = _text(_get(raw, "writing", where), f"{where}.writing")
    status = _get(raw, "status", where)
    if not isinstance(status, str) or status not in _STATUSES:
        raise _fail(
            f"{where}.status: unknown status {status!r} "
            f"(expected one of {sorted(_STATUSES)})"
        )
    place_id = _text(_get(raw, "place_id", where), f"{where}.place_id", optional=True)
    project = _text(_get(raw, "project", where), f"{where}.project", optional=True)
    if (status == "validated") != (place_id is not None):
        raise _fail(
            f"{where}: a validated writing needs a place_id, a rejected one has none"
        )
    return Decision(writing, place_id, cast(Status, status), project)


def _parse(
    data: object, local_places: set[str]
) -> tuple[str, dict[str, Place], list[Decision]]:
    if not isinstance(data, Mapping):
        raise _fail("the document must be a JSON object")
    fmt = _get(data, "format", "document")
    if not isinstance(fmt, str) or fmt != FORMAT:
        raise _fail(f"format {fmt!r} is not {FORMAT!r}")
    version = _get(data, "version", "document")
    if type(version) is not int or version != VERSION:
        raise _fail(
            f"version {version!r} is not supported (this atelier reads "
            f"version {VERSION}); upgrade the atelier"
        )
    exported_at = _get(data, "exported_at", "document")
    if not isinstance(exported_at, str):
        raise _fail("exported_at must be a string")
    raw_places = _get(data, "places", "document")
    if not isinstance(raw_places, list):
        raise _fail("places must be a list")
    raw_writings = _get(data, "writings", "document")
    if not isinstance(raw_writings, list):
        raise _fail("writings must be a list")
    places: dict[str, Place] = {}
    for index, raw in enumerate(raw_places):
        place = _parse_place(index, raw)
        if place.place_id in places:
            raise _fail(f"places[{index}]: duplicate place_id {place.place_id!r}")
        places[place.place_id] = place
    writings: list[Decision] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_writings):
        decision = _parse_writing(index, raw)
        if decision.writing in seen:
            raise _fail(f"writings[{index}]: duplicate writing {decision.writing!r}")
        seen.add(decision.writing)
        pid = decision.place_id
        if pid is not None and pid not in places and pid not in local_places:
            raise _fail(
                f"writings[{index}]: place_id {pid!r} is neither in the document "
                "nor in the registry"
            )
        writings.append(decision)
    return exported_at, places, writings


# -- import ---------------------------------------------------------------


def _place_changes(place: Place, now: str) -> list[RowChange]:
    changes = [RowChange("places", {"place_id": place.place_id}, {"created_at": now})]
    for kind, value in place.fields.items():
        changes.append(
            RowChange(
                "place_fields",
                {"place_id": place.place_id, "kind": kind},
                {"value": value, "origin": place.origins[kind]},
            )
        )
    return changes


def _writing_change(decision: Decision, project: str | None, now: str) -> RowChange:
    return RowChange(
        "writings",
        {"writing": decision.writing},
        {
            "place_id": decision.place_id,
            "status": decision.status,
            "project": project,
            "decided_at": now,
        },
    )


@dataclass(frozen=True)
class ImportResult:
    """The conflicts left to settle, and the ``import`` journal entry written
    (``None`` if nothing was applied)."""

    conflicts: list[Conflict]
    entry_id: int | None


def import_registry(registry: PlaceRegistry, data: object) -> ImportResult:
    """Apply everything in ``data`` that does not conflict.

    ``data`` is untrusted (typically ``json.load`` output), hence typed
    ``object``: any mapping is accepted, anything else is a format error.
    See the module docstring. ``RegistryFormatError`` (nothing written) if
    ``data`` is not a valid export.

    The import is planned from a read of the registry, then applied in one
    transaction that first checks the plan still holds: every writing found
    absent is still absent, every place to create still missing, every
    place relied on still there. If another process changed them in
    between, nothing is written and the import is planned again (so a
    writing decided meanwhile becomes a conflict), up to
    ``_IMPORT_ATTEMPTS`` times (``RuntimeError`` beyond).
    """
    for _ in range(_IMPORT_ATTEMPTS):
        try:
            return _import_once(registry, data)
        except _PlanOutdated:
            continue
    raise RuntimeError(
        "the registry kept changing during the import; try the import again"
    )


_IMPORT_ATTEMPTS = 5


class _PlanOutdated(Exception):
    """The registry changed between planning an import and applying it."""


def _import_once(registry: PlaceRegistry, data: object) -> ImportResult:
    local_places = {place.place_id for place in registry.places()}
    exported_at, places, incoming = _parse(data, local_places)
    local = registry.decisions(d.writing for d in incoming)

    applied: list[Decision] = []
    conflicts: list[Conflict] = []
    for decision in incoming:
        current = local.get(decision.writing)
        if current is None:
            applied.append(decision)
        elif (current.status, current.place_id) != (decision.status, decision.place_id):
            place = places.get(decision.place_id) if decision.place_id else None
            conflicts.append(Conflict(decision.writing, current, decision, place))

    needed = {d.place_id for d in applied if d.place_id is not None}
    deferred = {c.incoming.place_id for c in conflicts} - needed
    now = _now()
    changes: list[RowChange] = []
    created: list[str] = []
    for place_id in sorted(places):
        if place_id not in local_places and place_id not in deferred:
            created.append(place_id)
            changes.extend(_place_changes(places[place_id], now))
    changes.extend(_writing_change(d, d.project, now) for d in applied)
    relied_on = needed - set(created)

    def plan_holds() -> None:
        # Runs inside the import transaction: nothing can change after it.
        if registry.decisions(d.writing for d in applied):
            raise _PlanOutdated
        if any(_known(registry, place_id) for place_id in created):
            raise _PlanOutdated
        if not all(_known(registry, place_id) for place_id in relied_on):
            raise _PlanOutdated

    entry = registry.apply_import(
        changes,
        None,
        {"exported_at": exported_at, "conflicts": [c.writing for c in conflicts]},
        check=plan_holds,
    )
    return ImportResult(conflicts, entry)


def _known(registry: PlaceRegistry, place_id: str) -> bool:
    try:
        registry.place(place_id)
    except KeyError:
        return False
    return True


def resolve_conflict(
    registry: PlaceRegistry,
    conflict: Conflict,
    keep: Literal["current", "incoming"],
    project: str | None,
) -> int | None:
    """Settle ``conflict``: keep the local decision, or apply the incoming one.

    Returns the journal entry written (``None`` when keeping the local one).

    ``"incoming"`` is one undoable ``import`` journal entry, decided under
    ``project``; it creates the incoming place first if the registry lacks it
    (``KeyError`` if the conflict does not carry that place). If the local
    decision no longer matches ``conflict.current`` (status or place), it
    raises ``StaleConflictError`` and writes nothing.
    """
    if keep == "current":
        return None
    if keep != "incoming":
        raise ValueError(f"keep must be 'current' or 'incoming', not {keep!r}")
    now = _now()
    changes: list[RowChange] = []
    place_id = conflict.incoming.place_id
    known = place_id is None or _known(registry, place_id)
    if not known:
        place = conflict.incoming_place
        if place is None or place.place_id != place_id:
            raise KeyError(place_id)
        changes.extend(_place_changes(place, now))
    changes.append(_writing_change(conflict.incoming, project, now))

    def still_current() -> None:
        # Runs inside the import transaction: nothing can change in between.
        local = registry.decision(conflict.writing)
        expected = (conflict.current.status, conflict.current.place_id)
        if local is None or (local.status, local.place_id) != expected:
            raise StaleConflictError(
                f"the decision on {conflict.writing!r} changed since the "
                "conflict was reported; import again to see the current conflict"
            )
        if place_id is not None and _known(registry, place_id) != known:
            raise StaleConflictError(
                f"place {place_id!r} was created or removed since the conflict "
                "was reported; import again"
            )

    return registry.apply_import(
        changes,
        project,
        {"resolved_conflict": conflict.writing, "keep": keep},
        check=still_current,
    )
