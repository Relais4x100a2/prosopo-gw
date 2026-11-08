"""Personal place registry (design § 6.3): places, decisions and their journal.

Storage
    One SQLite file (``schema.sql``, ``PRAGMA user_version = 2``) holding
    ``places`` (stable UUID4 ids), ``place_levels`` (the level chain of each
    place, one row per rank, validated and proposed levels together),
    ``place_attributes`` (the postal code, with its origin), ``writings``
    (writing → place, or ``rejected``) and ``journal`` (append-only).
    A version 1 file (fixed fields in ``place_fields``) is migrated on
    opening when reference data is given (``migrate.migrate_v1``: backup
    first, then one transaction); without it, ``SchemaVersionError``.

Chains
    ``validate`` and ``set_levels`` replace the whole chain of a place (ranks
    beyond the new chain are deleted) and its postal code; both check it with
    ``check_chain``. ``accept_proposal`` turns a proposed level into a
    validated one; ``refuse_proposal`` deletes it and renumbers the levels
    after it. ``known_places`` reads the validated levels only: the name key
    of a place is its first validated ``commune`` level, else its first
    validated level.

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
    flagged ``undone``. A ``migrate`` entry (schema migration) has no rows:
    it cannot be undone, nor can the version 1 entries before it.

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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, cast, get_args

from ..places.cluster import KnownPlace, finer_key, name_key
from ..places.levels import (
    HistoricalNature,
    Level,
    LevelOrigin,
    LevelStatus,
    ViewField,
    check_chain,
    french_view,
    renumber,
    validated,
)
from ..refdata import RefData
from .migrate import migrate_v1

Status = Literal["validated", "rejected"]
PostalOrigin = Literal["written", "rule", "manual", "insee"]

SCHEMA_VERSION = 2

_LEVEL_COLUMNS = (
    "name",
    "written",
    "type",
    "identifier",
    "source",
    "start",
    "end",
    "latitude",
    "longitude",
    "nature",
    "origin",
    "status",
)

# table -> (key columns, state columns), in dependency order.
_TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "places": (("place_id",), ("created_at",)),
    "place_levels": (("place_id", "rank"), _LEVEL_COLUMNS),
    "place_attributes": (("place_id", "name"), ("value", "origin")),
    "writings": (("writing",), ("place_id", "status", "project", "decided_at")),
}
_ORDER = list(_TABLES)
_LEVEL_ORIGINS = frozenset(get_args(LevelOrigin))
_LEVEL_STATUSES = frozenset(get_args(LevelStatus))
_NATURES = frozenset(get_args(HistoricalNature))
_POSTAL_ORIGINS = frozenset(get_args(PostalOrigin))
_POSTAL = "postal_code"
_CHUNK = 500

State = dict[str, Any]


class SchemaVersionError(RuntimeError):
    """The registry file is of another schema version (newer, or to migrate)."""


@dataclass(frozen=True)
class Place:
    place_id: str
    levels: tuple[Level, ...]
    """Validated and proposed levels, by rank."""
    postal_code: str | None = None
    postal_origin: LevelOrigin | None = None

    @property
    def fields(self) -> dict[ViewField, str]:
        """French fixed-field view of the validated levels (``french_view``)."""
        return french_view(self.levels, self.postal_code)


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

    ``table`` is ``places`` (state ``created_at``), ``place_levels`` (key
    ``place_id``, ``rank``; state the ``Level`` fields but ``rank``),
    ``place_attributes`` (key ``place_id``, ``name``; state ``value``,
    ``origin``) or ``writings`` (key ``writing``; state ``place_id``,
    ``status``, ``project``, ``decided_at``).
    """

    table: str
    key: Mapping[str, Any]
    after: Mapping[str, Any] | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row_id(table: str, key: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    return table, tuple(key[column] for column in _TABLES[table][0])


def _quote(column: str) -> str:
    return f'"{column}"'


def _level_state(level: Level) -> State:
    return {column: getattr(level, column) for column in _LEVEL_COLUMNS}


def _level(rank: int, row: Sequence[Any]) -> Level:
    state = dict(zip(_LEVEL_COLUMNS, row, strict=True))
    return Level(rank=rank, **state)


def _check_levels(levels: Sequence[Level]) -> None:
    check_chain(levels)
    for level in levels:
        if level.origin not in _LEVEL_ORIGINS:
            raise ValueError(f"unknown level origin: {level.origin!r}")
        if level.status not in _LEVEL_STATUSES:
            raise ValueError(f"unknown level status: {level.status!r}")
        if level.nature is not None and level.nature not in _NATURES:
            raise ValueError(f"unknown historical nature: {level.nature!r}")


def _check_postal(postal_code: str | None, postal_origin: LevelOrigin | None) -> None:
    if (postal_code is None) != (postal_origin is None):
        raise ValueError("postal_code and postal_origin go together")
    if postal_origin is not None and postal_origin not in _POSTAL_ORIGINS:
        raise ValueError(f"unknown postal code origin: {postal_origin!r}")


def _known_place(place_id: str, levels: Sequence[Level]) -> KnownPlace | None:
    """Anchor of a place, read on its validated levels.

    The head of the chain is its first ``commune`` or ``commune_historique``
    level; a level before it (``Wazemmes`` in ``Wazemmes, Lille``) is recorded
    as ``finer``, so the place anchors only clusters with that same finer level.
    ``None`` without any validated level, or when the head is a
    ``commune_historique`` without code (no key would tell it from the current
    commune of that name).
    """
    chain = validated(levels)
    if not chain:
        return None
    department = next((lv.identifier for lv in chain if lv.type == "departement"), None)
    finer = finer_key(chain)
    head = next(
        (lv for lv in chain if lv.type in ("commune", "commune_historique")), None
    )
    if head is not None and head.type == "commune_historique":
        if head.identifier is None:
            return None
        key = name_key(head.name)
        return KnownPlace(
            place_id, None, key, department, f"{head.identifier}|{key}", finer
        )
    named = head if head is not None else chain[0]
    insee = head.identifier if head is not None else None
    return KnownPlace(place_id, insee, name_key(named.name), department, finer=finer)


class PlaceRegistry:
    """The user's personal place registry, stored in one SQLite file.

    Safe to share between threads (calls are serialized) and between
    processes (WAL, ``busy_timeout``, ``BEGIN IMMEDIATE`` transactions).
    """

    def __init__(self, path: Path, ref: RefData | None = None) -> None:
        """Open (or create) the registry at ``path``.

        ``ref`` is the reference data a schema migration reads: a version 1
        file is migrated with it (``migrate_v1``), and refused without it.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._ref = ref
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
            if version == 1:
                if ref is None:
                    raise SchemaVersionError(
                        f"{path} : référentiel en version 1 ; sa migration vers "
                        f"la version {SCHEMA_VERSION} nécessite les données de "
                        "référence"
                    )
                migrate_v1(self._conn, path, ref)
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
        """Every place with its chain and postal code, sorted by id."""
        with self._lock:
            ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT place_id FROM places ORDER BY place_id"
                )
            ]
            levels = self._levels_by_place()
            postal = self._postal_by_place()
        return [self._place(i, levels, postal) for i in ids]

    def place(self, place_id: str) -> Place:
        """The place ``place_id``; ``KeyError`` if unknown."""
        with self._lock:
            if not self._place_exists(place_id):
                raise KeyError(place_id)
            levels = self._levels_by_place(place_id)
            postal = self._postal_by_place(place_id)
        return self._place(place_id, levels, postal)

    def known_places(self) -> list[KnownPlace]:
        """Places with a validated level, as anchors for ``build_clusters``
        (by ``place_id``); read on their validated levels only."""
        with self._lock:
            levels = self._levels_by_place()
        known = (
            _known_place(place_id, chain) for place_id, chain in sorted(levels.items())
        )
        return [k for k in known if k is not None]

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
        levels: Sequence[Level],
        postal_code: str | None,
        postal_origin: LevelOrigin | None,
        project: str,
        place_id: str | None = None,
    ) -> Validation:
        """Attach ``writings`` to one place and set its chain and postal code.

        Returns the place id and the journal entry written.

        Without ``place_id`` a new place (UUID4) is created; with it, that
        place's chain and postal code are replaced by the given ones
        (``KeyError`` if unknown): a caller attaching a writing to an existing
        place must pass its stored chain and postal code to keep them.
        ``levels`` must pass ``check_chain`` (``ValueError``); ``postal_code``
        and ``postal_origin`` are both given or both ``None`` (no postal code).
        A writing decided otherwise before is re-attached; its previous row is
        journaled.
        """
        unique = list(dict.fromkeys(writings))
        if not unique:
            raise ValueError("validate needs at least one writing")
        _check_levels(levels)
        _check_postal(postal_code, postal_origin)
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
            changes += self._chain_changes(place_id, levels, postal_code, postal_origin)
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
        do ``set_levels``, the proposal decisions and ``detach``.
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

    def set_levels(
        self,
        place_id: str,
        levels: Sequence[Level],
        postal_code: str | None,
        postal_origin: LevelOrigin | None,
        project: str,
    ) -> int | None:
        """Replace the whole chain and postal code of a place (``correct``).

        Same checks as ``validate``; ``KeyError`` if the place is unknown.
        """
        _check_levels(levels)
        _check_postal(postal_code, postal_origin)
        with self._transaction():
            if not self._place_exists(place_id):
                raise KeyError(place_id)
            changes = self._chain_changes(place_id, levels, postal_code, postal_origin)
            return self._record("correct", project, changes, {"place_id": place_id})

    def accept_proposal(self, place_id: str, rank: int, project: str) -> int | None:
        """Validate the proposed level ``rank`` of a place (``correct``).

        ``KeyError`` if the place is unknown, ``ValueError`` if it has no
        proposed level at ``rank``.
        """
        with self._transaction():
            level = self._proposal(place_id, rank)
            change = RowChange(
                "place_levels",
                {"place_id": place_id, "rank": rank},
                _level_state(replace(level, status="validated")),
            )
            return self._record(
                "correct", project, [change], {"place_id": place_id, "rank": rank}
            )

    def refuse_proposal(self, place_id: str, rank: int, project: str) -> int | None:
        """Delete the proposed level ``rank`` and renumber the levels after it
        (``correct``); same errors as ``accept_proposal``."""
        with self._transaction():
            self._proposal(place_id, rank)
            levels = self._levels_by_place(place_id).get(place_id, ())
            kept = renumber([level for level in levels if level.rank != rank])
            check_chain(kept)
            changes = self._level_changes(place_id, kept, len(levels))
            return self._record(
                "correct", project, changes, {"place_id": place_id, "rank": rank}
            )

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
            if action == "migrate":
                backup = json.loads(payload).get("backup")
                raise ValueError(
                    f"la migration ne s'annule pas ; la sauvegarde est {backup}"
                )
            migrated = self._conn.execute(
                "SELECT MIN(entry_id) FROM journal WHERE action = 'migrate' "
                "AND entry_id > ?",
                (entry_id,),
            ).fetchone()[0]
            if migrated is not None:
                raise ValueError(
                    f"l'entrée {entry_id} précède la migration du référentiel "
                    f"(entrée {migrated}) et ne s'annule plus"
                )
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

    def _levels_by_place(
        self, place_id: str | None = None
    ) -> dict[str, tuple[Level, ...]]:
        """Chains of every place (or of ``place_id``) having levels, by rank."""
        sql = f"SELECT place_id, rank, {', '.join(map(_quote, _LEVEL_COLUMNS))} "
        sql += "FROM place_levels "
        params: tuple[str, ...] = ()
        if place_id is not None:
            sql += "WHERE place_id = ? "
            params = (place_id,)
        rows = self._conn.execute(sql + "ORDER BY place_id, rank", params)
        chains: dict[str, list[Level]] = {}
        for row in rows:
            chains.setdefault(row[0], []).append(_level(row[1], row[2:]))
        return {key: tuple(chain) for key, chain in chains.items()}

    def _postal_by_place(
        self, place_id: str | None = None
    ) -> dict[str, tuple[str, LevelOrigin]]:
        sql = "SELECT place_id, value, origin FROM place_attributes WHERE name = ?"
        params: tuple[str, ...] = (_POSTAL,)
        if place_id is not None:
            sql += " AND place_id = ?"
            params += (place_id,)
        return {
            row[0]: (row[1], cast(LevelOrigin, row[2]))
            for row in self._conn.execute(sql, params)
        }

    @staticmethod
    def _place(
        place_id: str,
        levels: Mapping[str, tuple[Level, ...]],
        postal: Mapping[str, tuple[str, LevelOrigin]],
    ) -> Place:
        code, origin = postal.get(place_id, (None, None))
        return Place(place_id, levels.get(place_id, ()), code, origin)

    def _proposal(self, place_id: str, rank: int) -> Level:
        """The proposed level ``rank`` of a place (see ``accept_proposal``)."""
        if not self._place_exists(place_id):
            raise KeyError(place_id)
        levels = self._levels_by_place(place_id).get(place_id, ())
        level = next((lv for lv in levels if lv.rank == rank), None)
        if level is None or level.status != "proposed":
            raise ValueError(f"place {place_id} has no proposed level at rank {rank}")
        return level

    def _level_changes(
        self, place_id: str, levels: Sequence[Level], previous: int
    ) -> list[RowChange]:
        """Rows writing ``levels`` over a chain of ``previous`` levels."""
        changes = [
            RowChange(
                "place_levels",
                {"place_id": place_id, "rank": level.rank},
                _level_state(level),
            )
            for level in levels
        ]
        changes += [
            RowChange("place_levels", {"place_id": place_id, "rank": rank}, None)
            for rank in range(len(levels), previous)
        ]
        return changes

    def _chain_changes(
        self,
        place_id: str,
        levels: Sequence[Level],
        postal_code: str | None,
        postal_origin: LevelOrigin | None,
    ) -> list[RowChange]:
        """Rows replacing the chain and postal code of ``place_id``."""
        previous = self._conn.execute(
            "SELECT COALESCE(MAX(rank) + 1, 0) FROM place_levels WHERE place_id = ?",
            (place_id,),
        ).fetchone()[0]
        changes = self._level_changes(place_id, levels, previous)
        changes.append(
            RowChange(
                "place_attributes",
                {"place_id": place_id, "name": _POSTAL},
                None
                if postal_code is None
                else {"value": postal_code, "origin": postal_origin},
            )
        )
        return changes

    def _place_exists(self, place_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM places WHERE place_id = ?", (place_id,)
            ).fetchone()
            is not None
        )

    def _read(self, table: str, key: Mapping[str, Any]) -> State | None:
        keys, columns = _TABLES[table]
        where = " AND ".join(f"{_quote(k)} = ?" for k in keys)
        row = self._conn.execute(
            f"SELECT {', '.join(map(_quote, columns))} FROM {table} WHERE {where}",
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
            names = ", ".join(map(_quote, keys + columns))
            marks = ", ".join("?" * (len(keys) + len(columns)))
            update = ", ".join(f"{_quote(c)} = excluded.{_quote(c)}" for c in columns)
            self._conn.execute(
                f"INSERT INTO {r['table']} ({names}) VALUES ({marks}) "
                f"ON CONFLICT ({', '.join(map(_quote, keys))}) DO UPDATE SET {update}",
                [r["key"][k] for k in keys] + [r["after"][c] for c in columns],
            )
        for r in deletes:
            keys, _ = _TABLES[r["table"]]
            where = " AND ".join(f"{_quote(k)} = ?" for k in keys)
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
            rows = json.loads(payload).get("rows", [])
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
        for table in ("place_levels", "place_attributes", "writings"):
            keys, _ = _TABLES[table]
            columns = ", ".join(map(_quote, keys))
            for row in self._conn.execute(
                f"SELECT {columns} FROM {table} WHERE place_id = ?", (place_id,)
            ).fetchall():
                key = dict(zip(keys, row, strict=True))
                if _row_id(table, key) not in touched:
                    self._conflict(entry_id, table, key)
