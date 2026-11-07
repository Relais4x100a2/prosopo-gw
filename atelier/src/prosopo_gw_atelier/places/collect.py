"""Collection of place writings from the ``core`` tables.

Collected columns and the occurrence they produce:

- ``personnes.naissance_lieu``: event type ``"naissance"``, date ``naissance_date``;
- ``personnes.deces_lieu``: event type ``"deces"``, date ``deces_date``;
- ``familles.mariage_lieu``: event type ``"mariage"``, date ``mariage_date``;
- ``evenements.lieu``: the row's own ``type`` (GeneWeb code) and ``date``.

``row_id`` is the value of the table's primary key. Every non-blank cell is one
occurrence: a birth present in ``personnes`` and in ``evenements`` counts twice,
consistently with the pivot columns. The writing key is ``parse_place(raw).name``
(complement removed); the complement stays on the occurrence.
"""

from __future__ import annotations

from collections.abc import Sequence

# geneweb-py ships no ``py.typed`` marker (PEP 561), so mypy does not read its
# annotations from the installed package.
from geneweb_py.core.place import parse_place
from geneweb_py.formats.tables import Row, Table

from .model import Occurrence, Writing

# table -> (place column, fixed event type or None, column of the event type,
# date column)
_PLACE_COLUMNS: dict[str, tuple[tuple[str, str | None, str | None, str], ...]] = {
    "personnes": (
        ("naissance_lieu", "naissance", None, "naissance_date"),
        ("deces_lieu", "deces", None, "deces_date"),
    ),
    "familles": (("mariage_lieu", "mariage", None, "mariage_date"),),
    "evenements": (("lieu", None, "type", "date"),),
}


def _text(row: Row, column: str | None) -> str | None:
    if column is None:
        return None
    value = row.get(column)
    if value is None:
        return None
    return str(value)


def collect_writings(tables: Sequence[Table]) -> dict[str, Writing]:
    """Return the place writings of the tables, in order of first appearance."""
    writings: dict[str, Writing] = {}
    for table in tables:
        columns = _PLACE_COLUMNS.get(table.spec.name)
        if columns is None:
            continue
        key = table.spec.primary_key
        for row in table.rows:
            row_id = _text(row, key) or ""
            for column, fixed_type, type_column, date_column in columns:
                raw = row.get(column)
                if not isinstance(raw, str):
                    continue
                parsed = parse_place(raw)
                if parsed is None or not parsed.name:
                    continue
                occurrence = Occurrence(
                    table=table.spec.name,
                    row_id=row_id,
                    column=column,
                    complement=parsed.complement,
                    event_type=fixed_type or _text(row, type_column),
                    date=_text(row, date_column),
                )
                writing = writings.setdefault(parsed.name, Writing(parsed.name))
                writing.occurrences.append(occurrence)
    return writings
