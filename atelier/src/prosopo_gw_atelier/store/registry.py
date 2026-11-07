"""Personal place registry (design § 6.3): places, decisions and their journal.

Storage
    One SQLite file (``schema.sql``, ``PRAGMA user_version = 1``) holding
    ``places`` (stable UUID4 ids), ``place_fields`` (one row per element kind,
    with its origin), ``writings`` (writing → place, or ``rejected``) and
    ``journal`` (append-only).

Journal
    Every public mutation is one transaction that changes rows and appends one
    journal entry, whose id it returns (``None`` when no row changes and
    nothing is journaled): callers never have to guess it from the latest
    entry, which another process sharing the file may have written. Its JSON
    payload lists every row it touched, with the full row state before and
    after (``None`` = no row)::

        {"rows": [{"table": "writings", "key": {"writing": "Roubaix"},
                   "before": null,
                   "after": {"place_id": "…", "status": "validated",
                             "project": "p", "decided_at": "…"}}, …],
         "details": {…}}

    An ``undo`` entry carries ``{"undone_entry": <id>, "rows": [...]}`` with
    the inverse changes. Entries are never deleted; an undone entry is only
    flagged ``undone``.

Undo
    ``undo(id)`` puts back the "before" state of every row the entry touched.
    It is exact only if those rows are still in the entry's "after" state, and
    if nothing outside the entry still points at a place the undo would
    delete. Otherwise a later entry changed them: ``undo`` raises
    ``ValueError`` naming the latest such entry and writes nothing, rather than
    silently overwriting newer decisions. Undo that later entry first.

Import (for the registry import)
    ``apply_import(changes, project, details)`` takes the desired "after"
    state of each row (``RowChange``), reads the "before" states itself,
    applies everything in one transaction and journals an ``import`` entry
    that ``undo`` reverses like any other.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, cast, get_args

from ..places.cluster import KnownPlace, name_key
from ..places.model import ElementKind

Origin = Literal["rule", "manual", "reference", "llm"]
Status = Literal["validated", "rejected"]

SCHEMA_VERSION = 1

# table -> (key columns, state columns), in dependency order.
_TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "places": (("place_id",), ("created_at",)),
    "place_fields": (("place_id", "kind"), ("value", "origin")),
    "writings": (("writing",), ("place_id", "status", "project", "decided_at")),
}
_ORDER = list(_TABLES)
_KINDS = frozenset(get_args(ElementKind))
_ORIGINS = frozenset(get_args(Origin))
_CHUNK = 500

State = dict[str, Any]


class SchemaVersionError(RuntimeError):
    """The registry file was written by a newer version of the atelier."""


@dataclass(frozen=True)
class Place:
    place_id: str
    fields: dict[ElementKind, str]
    origins: dict[ElementKind, Origin]


@dataclass(frozen=True)
class Decision:
    writing: str
    place_id: str | None
    status: Status
    project: str | None


@dataclass(frozen=True)
class Validation:
    """Result of ``validate``: the place, and the journal entry written
    (``None`` if nothing changed)."""

    place_id: str
    entry_id: int | None


@dataclass(frozen=True)
class JournalEntry:
    entry_id: int
    at: str
    project: str | None
    action: str
    payload: dict[str, Any]
    undone: bool


@dataclass(frozen=True)
class RowChange:
    """Desired state of one row: ``after=None`` deletes it.

    ``table`` is ``places`` (state ``created_at``), ``place_fields`` (key
    ``place_id``, ``kind``; state ``value``, ``origin``) or ``writings`` (key
    ``writing``; state ``place_id``, ``status``, ``project``, ``decided_at``).
    """

    table: str
    key: Mapping[str, str]
    after: Mapping[str, Any] | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row_id(table: str, key: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    return table, tuple(key[column] for column in _TABLES[table][0])


class PlaceRegistry:
    """The user's personal place registry, stored in one SQLite file.

    Safe to share between threads (calls are serialized) and between
    processes (WAL, ``busy_timeout``, ``BEGIN IMMEDIATE`` transactions).
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False
        )
        try:
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"{path}: registry schema version {version} is newer than "
                    f"the supported version {SCHEMA_VERSION}; upgrade the atelier"
                )
            if version == 0:
                schema = files(__package__).joinpath("schema.sql").read_text("utf-8")
                self._conn.executescript(f"BEGIN IMMEDIATE;\n{schema}\nCOMMIT;")
        except BaseException:
            self._conn.close()
            raise

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> PlaceRegistry:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- reads --------------------------------------------------------------

    def decision(self, writing: str) -> Decision | None:
        return self.decisions([writing]).get(writing)

    def decisions(self, writings: Iterable[str]) -> dict[str, Decision]:
        """Decisions of the decided ``writings`` (undecided ones are absent)."""
        wanted = list(dict.fromkeys(writings))
        result: dict[str, Decision] = {}
        with self._lock:
            for start in range(0, len(wanted), _CHUNK):
                chunk = wanted[start : start + _CHUNK]
                marks = ",".join("?" * len(chunk))
                rows = self._conn.execute(
                    "SELECT writing, place_id, status, project FROM writings "
                    f"WHERE writing IN ({marks})",
                    chunk,
                ).fetchall()
                for writing, place_id, status, project in rows:
                    result[writing] = Decision(
                        writing, place_id, cast(Status, status), project
                    )
        return result

    def all_decisions(self) -> list[Decision]:
        """Every decision, sorted by writing (for the registry export)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT writing, place_id, status, project FROM writings "
                "ORDER BY writing"
            ).fetchall()
        return [
            Decision(writing, place_id, cast(Status, status), project)
            for writing, place_id, status, project in rows
        ]

    def places(self) -> list[Place]:
        """Every place with its fields and origins, sorted by id."""
        with self._lock:
            ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT place_id FROM places ORDER BY place_id"
                )
            ]
            rows = self._conn.execute(
                "SELECT place_id, kind, value, origin FROM place_fields ORDER BY kind"
            ).fetchall()
        by_place: dict[str, Place] = {i: Place(i, {}, {}) for i in ids}
        for place_id, kind, value, origin in rows:
            by_place[place_id].fields[cast(ElementKind, kind)] = value
            by_place[place_id].origins[cast(ElementKind, kind)] = cast(Origin, origin)
        return list(by_place.values())

    def place(self, place_id: str) -> Place:
        """The place ``place_id``; ``KeyError`` if unknown."""
        with self._lock:
            if not self._place_exists(place_id):
                raise KeyError(place_id)
            rows = self._conn.execute(
                "SELECT kind, value, origin FROM place_fields WHERE place_id = ? "
                "ORDER BY kind",
                (place_id,),
            ).fetchall()
        fields = {cast(ElementKind, kind): value for kind, value, _ in rows}
        origins = {cast(ElementKind, kind): cast(Origin, o) for kind, _, o in rows}
        return Place(place_id, fields, origins)

    def known_places(self) -> list[KnownPlace]:
        """Validated places, as anchors for ``build_clusters`` (by ``place_id``)."""
        with self._lock:
            ids = [r[0] for r in self._conn.execute("SELECT place_id FROM places")]
            rows = self._conn.execute(
                "SELECT place_id, kind, value FROM place_fields "
                "WHERE kind IN ('commune', 'former_name', 'insee_code', 'department')"
            ).fetchall()
        by_place: dict[str, dict[str, str]] = {place_id: {} for place_id in ids}
        for place_id, kind, value in rows:
            by_place[place_id][kind] = value
        return [
            KnownPlace(
                place_id=place_id,
                insee=fields.get("insee_code"),
                name_key=name_key(
                    fields.get("commune") or fields.get("former_name", "")
                ),
                department=fields.get("department"),
            )
            for place_id, fields in sorted(by_place.items())
        ]

    def journal(self, limit: int | None = None) -> list[JournalEntry]:
        """Journal entries, latest first (the ``limit`` latest when given)."""
        sql = "SELECT entry_id, at, project, action, payload, undone FROM journal "
        sql += "ORDER BY entry_id DESC"
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            JournalEntry(
                entry_id, at, project, action, json.loads(payload), bool(undone)
            )
            for entry_id, at, project, action, payload, undone in rows
        ]

    # -- mutations ----------------------------------------------------------

    def validate(
        self,
        writings: Sequence[str],
        fields: Mapping[ElementKind, str | None],
        origins: Mapping[ElementKind, Origin],
        project: str,
        place_id: str | None = None,
    ) -> Validation:
        """Attach ``writings`` to one place and set its ``fields``.

        Returns the place id and the journal entry written.

        Without ``place_id`` a new place (UUID4) is created; with it, the
        given fields are merged into that place (``KeyError`` if unknown).
        ``origins`` must give the origin of each field set. A field given as
        ``None`` is removed from the place (journaled, so undo restores its
        value and origin); it takes no origin. A writing decided otherwise
        before is re-attached; its previous row is journaled.
        """
        unique = list(dict.fromkeys(writings))
        if not unique:
            raise ValueError("validate needs at least one writing")
        for kind in fields:
            self._check_kind(kind)
        if {k for k, v in fields.items() if v is not None} != set(origins):
            raise ValueError(
                "origins must give the origin of each field, and only those"
            )
        for kind, origin in origins.items():
            self._check_kind(kind)
            if origin not in _ORIGINS:
                raise ValueError(f"unknown origin: {origin!r}")
        now = _now()
        with self._transaction():
            changes: list[RowChange] = []
            if place_id is None:
                place_id = str(uuid.uuid4())
                changes.append(
                    RowChange("places", {"place_id": place_id}, {"created_at": now})
                )
            elif not self._place_exists(place_id):
                raise KeyError(place_id)
            for kind, value in fields.items():
                changes.append(
                    RowChange(
                        "place_fields",
                        {"place_id": place_id, "kind": kind},
                        None
                        if value is None
                        else {"value": value, "origin": origins[kind]},
                    )
                )
            for writing in unique:
                changes.append(
                    RowChange(
                        "writings",
                        {"writing": writing},
                        {
                            "place_id": place_id,
                            "status": "validated",
                            "project": project,
                            "decided_at": now,
                        },
                    )
                )
            entry = self._record("validate", project, changes, {"place_id": place_id})
        return Validation(place_id, entry)

    def reject(self, writings: Sequence[str], project: str) -> int | None:
        """Mark ``writings`` as not a usable place (e.g. "en mer").

        Returns the journal entry written (``None`` if nothing changed), as
        do ``correct`` and ``detach``.
        """
        now = _now()
        changes = [
            RowChange(
                "writings",
                {"writing": writing},
                {
                    "place_id": None,
                    "status": "rejected",
                    "project": project,
                    "decided_at": now,
                },
            )
            for writing in dict.fromkeys(writings)
        ]
        with self._transaction():
            return self._record("reject", project, changes, {})

    def correct(
        self, place_id: str, field: ElementKind, value: str | None, project: str
    ) -> int | None:
        """Set ``field`` of a place by hand: its origin becomes ``manual``.

        ``value=None`` removes the field (journaled; undo restores it).
        """
        self._check_kind(field)
        with self._transaction():
            if not self._place_exists(place_id):
                raise KeyError(place_id)
            change = RowChange(
                "place_fields",
                {"place_id": place_id, "kind": field},
                None if value is None else {"value": value, "origin": "manual"},
            )
            return self._record("correct", project, [change], {"place_id": place_id})

    def detach(self, writings: Sequence[str], project: str) -> int | None:
        """Make ``writings`` undecided again; their place stays."""
        changes = [
            RowChange("writings", {"writing": writing}, None)
            for writing in dict.fromkeys(writings)
        ]
        with self._transaction():
            return self._record("detach", project, changes, {})

    def apply_import(
        self,
        changes: Sequence[RowChange],
        project: str | None,
        details: Mapping[str, Any] | None = None,
        check: Callable[[], None] | None = None,
    ) -> int | None:
        """Apply ``changes`` as one undoable ``import`` journal entry.

        The "before" state of each row is read from the registry. Returns the
        entry id, or ``None`` when no row actually changes (nothing journaled).
        ``check``, if given, runs first inside the same transaction (it may
        read the registry); an exception it raises aborts with nothing written.
        """
        with self._transaction():
            if check is not None:
                check()
            return self._record("import", project, changes, dict(details or {}))

    def undo(self, entry_id: int) -> int:
        """Restore the state before entry ``entry_id`` (see the module docstring).

        Returns the id of the ``undo`` entry written.
        """
        with self._transaction():
            row = self._conn.execute(
                "SELECT action, payload, undone FROM journal WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"no journal entry {entry_id}")
            action, payload, undone = row
            if action == "undo":
                raise ValueError(f"entry {entry_id} is an undo and cannot be undone")
            if undone:
                raise ValueError(f"entry {entry_id} is already undone")
            rows: list[State] = json.loads(payload)["rows"]
            touched = {_row_id(r["table"], r["key"]) for r in rows}
            for r in rows:
                if self._read(r["table"], r["key"]) != r["after"]:
                    self._conflict(entry_id, r["table"], r["key"])
            for r in rows:
                if r["table"] == "places" and r["before"] is None:
                    self._check_unreferenced(entry_id, r["key"]["place_id"], touched)
            inverse = [
                {
                    "table": r["table"],
                    "key": r["key"],
                    "before": r["after"],
                    "after": r["before"],
                }
                for r in rows
            ]
            self._apply(inverse)
            self._conn.execute(
                "UPDATE journal SET undone = 1 WHERE entry_id = ?", (entry_id,)
            )
            return self._append_journal(
                "undo", None, {"undone_entry": entry_id, "rows": inverse}
            )

    # -- internals ----------------------------------------------------------

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    @staticmethod
    def _check_kind(kind: str) -> None:
        if kind not in _KINDS:
            raise ValueError(f"unknown element kind: {kind!r}")

    def _place_exists(self, place_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM places WHERE place_id = ?", (place_id,)
            ).fetchone()
            is not None
        )

    def _read(self, table: str, key: Mapping[str, Any]) -> State | None:
        keys, columns = _TABLES[table]
        where = " AND ".join(f"{k} = ?" for k in keys)
        row = self._conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE {where}",
            [key[k] for k in keys],
        ).fetchone()
        return None if row is None else dict(zip(columns, row, strict=True))

    def _record(
        self,
        action: str,
        project: str | None,
        changes: Sequence[RowChange],
        details: dict[str, Any],
    ) -> int | None:
        """Apply ``changes`` and journal them; ``None`` if nothing changes."""
        rows: list[State] = []
        seen: set[tuple[str, tuple[Any, ...]]] = set()
        for change in changes:
            if change.table not in _TABLES:
                raise ValueError(f"unknown table: {change.table!r}")
            keys, columns = _TABLES[change.table]
            if set(change.key) != set(keys):
                raise ValueError(f"{change.table} key must be {keys}")
            if change.after is not None and set(change.after) != set(columns):
                raise ValueError(f"{change.table} state must be {columns}")
            row_id = _row_id(change.table, change.key)
            if row_id in seen:
                raise ValueError(f"row changed twice in one entry: {row_id}")
            seen.add(row_id)
            key = {k: change.key[k] for k in keys}
            after = (
                None if change.after is None else {c: change.after[c] for c in columns}
            )
            before = self._read(change.table, key)
            if before != after:
                rows.append(
                    {
                        "table": change.table,
                        "key": key,
                        "before": before,
                        "after": after,
                    }
                )
        if not rows:
            return None
        self._apply(rows)
        return self._append_journal(action, project, {"rows": rows, "details": details})

    def _apply(self, rows: Sequence[State]) -> None:
        """Write the "after" state of ``rows``: upserts parents first, deletes last."""
        upserts = sorted(
            (r for r in rows if r["after"] is not None),
            key=lambda r: _ORDER.index(r["table"]),
        )
        deletes = sorted(
            (r for r in rows if r["after"] is None),
            key=lambda r: -_ORDER.index(r["table"]),
        )
        for r in upserts:
            keys, columns = _TABLES[r["table"]]
            names = ", ".join(keys + columns)
            marks = ", ".join("?" * (len(keys) + len(columns)))
            update = ", ".join(f"{c} = excluded.{c}" for c in columns)
            self._conn.execute(
                f"INSERT INTO {r['table']} ({names}) VALUES ({marks}) "
                f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {update}",
                [r["key"][k] for k in keys] + [r["after"][c] for c in columns],
            )
        for r in deletes:
            keys, _ = _TABLES[r["table"]]
            where = " AND ".join(f"{k} = ?" for k in keys)
            self._conn.execute(
                f"DELETE FROM {r['table']} WHERE {where}", [r["key"][k] for k in keys]
            )

    def _append_journal(self, action: str, project: str | None, payload: State) -> int:
        cursor = self._conn.execute(
            "INSERT INTO journal (at, project, action, payload) VALUES (?, ?, ?, ?)",
            (_now(), project, action, json.dumps(payload, ensure_ascii=False)),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _latest_touching(
        self, entry_id: int, table: str, key: Mapping[str, Any]
    ) -> int | None:
        target = _row_id(table, key)
        for later, payload in self._conn.execute(
            "SELECT entry_id, payload FROM journal WHERE entry_id > ? "
            "ORDER BY entry_id DESC",
            (entry_id,),
        ):
            rows = json.loads(payload)["rows"]
            if any(_row_id(r["table"], r["key"]) == target for r in rows):
                return int(later)
        return None

    def _conflict(self, entry_id: int, table: str, key: Mapping[str, Any]) -> None:
        later = self._latest_touching(entry_id, table, key)
        by = f"entry {later}" if later is not None else "a later change"
        raise ValueError(
            f"cannot undo entry {entry_id}: {table} {dict(key)} was changed "
            f"since by {by}; undo it first"
        )

    def _check_unreferenced(
        self, entry_id: int, place_id: str, touched: set[tuple[str, tuple[Any, ...]]]
    ) -> None:
        """Undoing a place creation: nothing outside the entry may still use it."""
        for table in ("place_fields", "writings"):
            keys, _ = _TABLES[table]
            for row in self._conn.execute(
                f"SELECT {', '.join(keys)} FROM {table} WHERE place_id = ?", (place_id,)
            ).fetchall():
                key = dict(zip(keys, row, strict=True))
                if _row_id(table, key) not in touched:
                    self._conflict(entry_id, table, key)
