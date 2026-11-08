"""Collection of place writings from the ``core`` tables.

Collected columns and the occurrence they produce:

- ``personnes.naissance_lieu``: event type ``"naissance"``, date ``naissance_date``;
  every occurrence also takes its ``year`` from the matching ``*_annee`` column
  (``naissance_annee``, ``deces_annee``, ``mariage_annee``, ``annee``);
- ``personnes.deces_lieu``: event type ``"deces"``, date ``deces_date``;
- ``familles.mariage_lieu``: event type ``"mariage"``, date ``mariage_date``;
- ``evenements.lieu``: the row's own ``type`` (GeneWeb code) and ``date``.

``row_id`` is the value of the table's primary key. Every non-blank cell is one
occurrence, except an event row that repeats a column: GeneWeb keeps a birth,
death or marriage both in the person/family (``naissance_lieu``, ``deces_lieu``,
``mariage_lieu``) and as a ``#birt``/``#deat``/``#marr`` event. When the event
has the same owner, the matching code and the same place (writing and
complement), the pair is one occurrence: the column, unless only the event is
dated (then the event, which says more). A column absorbs at most one event.
Only the counts and the occurrence list are deduplicated: the pivot still fills
``lieu_id`` on both rows, since both cells exist in ``core``'s tables.
The writing key is ``parse_place(raw).name`` (complement removed); the
complement stays on the occurrence.
"""

from __future__ import annotations

from collections.abc import Sequence

# geneweb-py ships no ``py.typed`` marker (PEP 561), so mypy does not read its
# annotations from the installed package.
from geneweb_py.core.place import parse_place
from geneweb_py.formats.tables import Row, Table, Value

from .model import Occurrence, Writing

# table -> (place column, fixed event type or None, column of the event type,
# date column, year column)
_PLACE_COLUMNS: dict[str, tuple[tuple[str, str | None, str | None, str, str], ...]] = {
    "personnes": (
        ("naissance_lieu", "naissance", None, "naissance_date", "naissance_annee"),
        ("deces_lieu", "deces", None, "deces_date", "deces_annee"),
    ),
    "familles": (("mariage_lieu", "mariage", None, "mariage_date", "mariage_annee"),),
    "evenements": (("lieu", None, "type", "date", "annee"),),
}


# event code -> (owner column of the event row, table, place column)
_REPEATED_COLUMNS: dict[str, tuple[str, str, str]] = {
    "birt": ("personne_id", "personnes", "naissance_lieu"),
    "deat": ("personne_id", "personnes", "deces_lieu"),
    "marr": ("famille_id", "familles", "mariage_lieu"),
}

# (table, row id, place column, writing, complement): a column occurrence an
# event row may repeat
_ColumnKey = tuple[str, str, str, str, str | None]


def _text(row: Row, column: str | None) -> str | None:
    if column is None:
        return None
    value = row.get(column)
    if value is None:
        return None
    return str(value)


def _year(row: Row, column: str) -> int | None:
    value = row.get(column)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def split_place(raw: Value) -> tuple[str, str | None] | None:
    """Writing key and complement of a place cell; ``None`` if it has no place.

    The key is ``parse_place(raw).name`` (complement removed), the key of the
    registry's decisions.
    """
    if not isinstance(raw, str):
        return None
    parsed = parse_place(raw)
    if parsed is None or not parsed.name:
        return None
    return parsed.name, parsed.complement


def _repeated_key(
    row: Row, event_type: str | None, text: str, complement: str | None
) -> _ColumnKey | None:
    """Key of the column an ``evenements`` row repeats, if its code has one."""
    repeated = _REPEATED_COLUMNS.get(event_type or "")
    if repeated is None:
        return None
    owner_column, table, column = repeated
    owner = _text(row, owner_column)
    if not owner:
        return None
    return table, owner, column, text, complement


def collect_writings(tables: Sequence[Table]) -> dict[str, Writing]:
    """Return the place writings of the tables, in order of first appearance.

    ``evenements`` is read after the other tables, so that an event repeating
    a person or family column (module docstring) finds it.
    """
    writings: dict[str, Writing] = {}
    columns_seen: dict[_ColumnKey, tuple[Writing, int]] = {}
    ordered = sorted(tables, key=lambda t: t.spec.name == "evenements")
    for table in ordered:
        columns = _PLACE_COLUMNS.get(table.spec.name)
        if columns is None:
            continue
        key = table.spec.primary_key
        is_event = table.spec.name == "evenements"
        for row in table.rows:
            row_id = _text(row, key) or ""
            for column, fixed_type, type_column, date_column, year_column in columns:
                split = split_place(row.get(column))
                if split is None:
                    continue
                text, complement = split
                occurrence = Occurrence(
                    table=table.spec.name,
                    row_id=row_id,
                    column=column,
                    complement=complement,
                    event_type=fixed_type or _text(row, type_column),
                    date=_text(row, date_column),
                    year=_year(row, year_column),
                )
                if is_event:
                    repeated = _repeated_key(
                        row, occurrence.event_type, text, complement
                    )
                    seen = columns_seen.pop(repeated, None) if repeated else None
                    if seen is not None:
                        writing, index = seen
                        kept = writing.occurrences[index]
                        if kept.date is None and occurrence.date is not None:
                            writing.occurrences[index] = occurrence
                        continue
                writing = writings.setdefault(text, Writing(text))
                if not is_event:
                    columns_seen[
                        (table.spec.name, row_id, column, text, complement)
                    ] = (writing, len(writing.occurrences))
                writing.occurrences.append(occurrence)
    return writings
