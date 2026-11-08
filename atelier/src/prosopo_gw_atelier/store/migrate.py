"""Migration of a version 1 registry (fixed fields) to level chains (version 2).

Backup first
    ``migrate_v1`` copies the whole file to ``backup_path`` (``<stem>.v1-<UTC
    timestamp>.sqlite``, next to it) with ``sqlite3.Connection.backup`` before
    any write. If the backup fails, nothing is changed and the error goes up.

One transaction
    Then, in one ``BEGIN IMMEDIATE`` transaction: ``place_levels`` and
    ``place_attributes`` are created, ``journal`` is rebuilt to admit the
    ``migrate`` action (entries and ids kept), every place is converted,
    ``place_fields`` is dropped and ``user_version`` becomes 2. If a converted
    chain fails ``check_chain``, everything is rolled back (the backup stays)
    and a ``ValueError`` names the place. A place left without validated level
    is named after its first validated writing (sorted), one untyped validated
    level of origin ``written``; a place with no level and no writing at all
    keeps no level (counted as ``empty``). A file already migrated by another
    process meanwhile is left alone (the redundant backup is removed).

Conversion of a place (``levels_from_v1``)
    ``commune`` (``insee_code`` as identifier; the COG name when only the code
    is set), ``department`` (a code or a name; its COG name, code as
    identifier), ``region`` (``ancienne_region`` for a pre-2016 region) and
    ``country`` become validated levels, in this order, with their v1 origin
    translated (``reference`` becomes ``insee``). ``postal_code`` is the place
    attribute. ``former_name`` recognised as a former commune (fusion,
    association, delegation) of the place's commune becomes a proposed
    ``commune_historique`` at rank 0; recognised as a rename, the ``written`` of
    the commune level; otherwise a proposed untyped level at rank 0.

Proposals from the writings (migration only)
    For every writing validated to the place, ``rule_levels(decompose(…))``
    is read: each ``written`` level whose normalized name the chain lacks is
    inserted as a proposed level, once per name, after the nearest level
    written before it that the chain has (before the nearest one written
    after it otherwise, and before the ``commune_historique`` levels of a
    commune, choice 8 of the plan).

Decisions and journal
    ``writings`` rows are kept line for line: no writing changes place. One
    ``migrate`` journal entry (``project`` NULL) records ``{"from": 1, "to": 2,
    "backup": <file name>, "places": n, "proposals": n, "empty": n}`` without
    rows: it cannot be undone, and neither can the version 1 entries before it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from ..places.decompose import decompose
from ..places.levels import Level, LevelOrigin, check_chain, renumber, rule_levels
from ..refdata import RefData, normalize

_ORIGINS: dict[str, LevelOrigin] = {
    "rule": "rule",
    "manual": "manual",
    "reference": "insee",
    "llm": "llm",
}
# place_attributes admits no ``llm`` origin: an LLM postal code becomes ``rule``.
_POSTAL_ORIGINS: dict[str, LevelOrigin] = {**_ORIGINS, "llm": "rule"}
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


def backup_path(path: Path, at: datetime) -> Path:
    """Backup file of the version 1 registry ``path``, taken at ``at``."""
    return path.with_name(f"{path.stem}.v1-{at:%Y%m%dT%H%M%S}.sqlite")


def _origin(
    origins: Mapping[str, str],
    kind: str,
    table: Mapping[str, LevelOrigin] = _ORIGINS,
) -> LevelOrigin:
    """Translated origin of the v1 field ``kind`` (``ValueError`` in French)."""
    value = origins.get(kind)
    if value is None:
        raise ValueError(f"Origine manquante pour le champ {kind}.")
    if value not in table:
        raise ValueError(f"Origine inconnue pour le champ {kind} : {value!r}.")
    return table[value]


def levels_from_v1(
    fields: Mapping[str, str], origins: Mapping[str, str], ref: RefData
) -> tuple[tuple[Level, ...], str | None, LevelOrigin | None]:
    """Chain, postal code and its origin of one version 1 place.

    ``fields`` and ``origins`` are keyed by v1 kind (``commune``,
    ``insee_code``…), origins in v1 values (``reference``…). The chain may
    hold a proposed level built from ``former_name``. A missing or unknown
    origin raises ``ValueError`` (French message).
    """
    source = f"COG {ref.cog_vintage}"
    levels: list[Level] = []
    insee = fields.get("insee_code")
    commune: Level | None = None
    name = fields.get("commune")
    if name or insee:
        origin = _origin(origins, "commune" if name else "insee_code")
        if not name and insee:
            known = ref.commune_by_insee(insee)
            name = known.name if known is not None else insee
        commune = Level(
            0,
            name or "",
            type="commune",
            identifier=insee,
            source=source if origin == "insee" else None,
            origin=origin,
        )
    department = fields.get("department")
    if department:
        code = ref.department(department)
        origin = _origin(origins, "department")
        levels.append(
            Level(
                0,
                (ref.department_name(code) if code else None) or department,
                type="departement",
                identifier=code,
                source=source if origin == "insee" else None,
                origin=origin,
            )
        )
    region = fields.get("region")
    if region:
        known_region = ref.region(region)
        origin = _origin(origins, "region")
        old = known_region is not None and known_region[1]
        levels.append(
            Level(
                0,
                region,
                type="ancienne_region" if old else "region",
                source=source if origin == "insee" else None,
                origin=origin,
            )
        )
    country = fields.get("country")
    if country:
        levels.append(
            Level(0, country, type="pays", origin=_origin(origins, "country"))
        )

    former_name = fields.get("former_name")
    proposal: Level | None = None
    if former_name:
        place_insee = insee.strip().upper() if insee else None
        former = next(
            (
                match.former
                for match in ref.communes_by_name(former_name)
                if match.former is not None and match.commune.insee == place_insee
            ),
            None,
        )
        if former is not None and former.nature == "renommage":
            if commune is not None:  # always set: place_insee comes with it
                commune = replace(commune, written=former_name)
        elif former is not None:
            proposal = Level(
                0,
                former.name,
                written=former_name if former_name != former.name else None,
                type="commune_historique",
                identifier=former.insee,
                source=source,
                end=former.date or None,
                nature=None if former.nature == "renommage" else former.nature,
                origin="insee",
                status="proposed",
            )
        else:
            proposal = Level(0, former_name, origin="written", status="proposed")
    chain = [
        *([proposal] if proposal else []),
        *([commune] if commune else []),
        *levels,
    ]
    postal = fields.get("postal_code") or None
    postal_origin = _origin(origins, "postal_code", _POSTAL_ORIGINS) if postal else None
    return renumber(chain), postal, postal_origin


def _find(levels: Sequence[Level], key: str) -> int | None:
    """Index of the first level whose name (or written form) normalizes to ``key``."""
    for index, level in enumerate(levels):
        if key in (normalize(level.name), normalize(level.written or "")):
            return index
    return None


def _position(levels: Sequence[Level], keys: Sequence[str], index: int) -> int:
    """Where the written level ``keys[index]`` goes in ``levels`` (choice 8)."""
    for key in reversed(keys[:index]):
        found = _find(levels, key)
        if found is not None:
            return found + 1
    for key in keys[index + 1 :]:
        found = _find(levels, key)
        if found is not None:
            while found > 0 and levels[found - 1].type == "commune_historique":
                found -= 1
            return found
    return len(levels)


def _writing_proposals(
    chain: Sequence[Level], writings: Sequence[str], ref: RefData
) -> tuple[Level, ...]:
    """``chain`` with the written levels of ``writings`` it lacks, proposed."""
    levels = list(chain)
    for writing in writings:
        written = rule_levels(decompose(writing, ref), ref)
        keys = [normalize(level.name) for level in written]
        for index, level in enumerate(written):
            if level.origin != "written" or not keys[index]:
                continue
            if _find(levels, keys[index]) is not None:
                continue
            position = _position(levels, keys, index)
            levels.insert(position, replace(level, status="proposed"))
    return renumber(levels)


def _statements(script: str) -> list[str]:
    """SQL statements of ``script`` (``executescript`` would commit first)."""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    return statements


def _convert(conn: sqlite3.Connection, ref: RefData, backup: str) -> None:
    """Body of the migration, inside its transaction."""
    place_ids = [r[0] for r in conn.execute("SELECT place_id FROM places")]
    fields: dict[str, dict[str, str]] = {}
    origins: dict[str, dict[str, str]] = {}
    for place_id, kind, value, origin in conn.execute(
        "SELECT place_id, kind, value, origin FROM place_fields"
    ):
        fields.setdefault(place_id, {})[kind] = value
        origins.setdefault(place_id, {})[kind] = origin
    writings: dict[str, list[str]] = {}
    for writing, place_id in conn.execute(
        "SELECT writing, place_id FROM writings WHERE status = 'validated' "
        "ORDER BY writing"
    ):
        writings.setdefault(place_id, []).append(writing)

    conn.execute("ALTER TABLE journal RENAME TO journal_v1")
    schema = files(__package__).joinpath("schema.sql").read_text("utf-8")
    for statement in _statements(schema):
        conn.execute(statement)
    conn.execute(
        "INSERT INTO journal (entry_id, at, project, action, payload, undone) "
        "SELECT entry_id, at, project, action, payload, undone FROM journal_v1"
    )
    conn.execute("DROP TABLE journal_v1")

    proposals = empty = 0
    columns = ", ".join(f'"{c}"' for c in ("place_id", "rank", *_LEVEL_COLUMNS))
    marks = ", ".join("?" * (2 + len(_LEVEL_COLUMNS)))
    for place_id in sorted(place_ids):
        attached = writings.get(place_id, [])
        try:
            chain, postal, postal_origin = levels_from_v1(
                fields.get(place_id, {}), origins.get(place_id, {}), ref
            )
            if not any(level.status == "validated" for level in chain) and attached:
                # No level to keep: the place is named after its first writing.
                fallback = Level(len(chain), attached[0], origin="written")
                chain = (*chain, fallback)
            chain = _writing_proposals(chain, attached, ref)
            if chain:
                check_chain(chain)
            else:
                empty += 1  # no level and no writing: kept as an orphan
        except ValueError as exc:
            raise ValueError(
                f"Migration du référentiel impossible pour le lieu {place_id} : "
                f"{exc} Le fichier n'a pas été modifié."
            ) from exc
        proposals += sum(level.status == "proposed" for level in chain)
        for level in chain:
            conn.execute(
                f"INSERT INTO place_levels ({columns}) VALUES ({marks})",
                (place_id, level.rank, *(getattr(level, c) for c in _LEVEL_COLUMNS)),
            )
        if postal is not None:
            conn.execute(
                "INSERT INTO place_attributes (place_id, name, value, origin) "
                "VALUES (?, 'postal_code', ?, ?)",
                (place_id, postal, postal_origin),
            )
    conn.execute("DROP TABLE place_fields")
    conn.execute("PRAGMA user_version = 2")
    payload = {
        "from": 1,
        "to": 2,
        "backup": backup,
        "places": len(place_ids),
        "proposals": proposals,
        "empty": empty,
    }
    conn.execute(
        "INSERT INTO journal (at, project, action, payload) "
        "VALUES (?, NULL, 'migrate', ?)",
        (
            datetime.now(UTC).isoformat(timespec="seconds"),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def migrate_v1(conn: sqlite3.Connection, path: Path, ref: RefData) -> None:
    """Back ``path`` up, then migrate it from version 1 to 2 (module docstring).

    ``conn`` is an open connection to ``path`` in autocommit mode
    (``isolation_level=None``).
    """
    backup = backup_path(path, datetime.now(UTC))
    try:
        target = sqlite3.connect(backup)
        try:
            conn.backup(target)
        finally:
            target.close()
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            # Migrated by another process since the caller read the version.
            conn.execute("ROLLBACK")
            backup.unlink(missing_ok=True)
            return
        _convert(conn, ref, backup.name)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
