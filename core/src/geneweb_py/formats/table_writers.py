"""Rendus des tables d'export : CSV, JSON, SQLite et dictionnaire des colonnes.

Voir ``core/doc/exports_design.md``. Les CSV sont en UTF-8 avec BOM, séparés par
``;`` (ouverture directe dans un Excel français) ; seul le CSV neutralise les
formules de tableur, le JSON et le SQLite gardent les valeurs telles quelles.
"""

import csv
import io
import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence

from .tables import Column, ColumnType, Table, TableSpec, Value

BOM = "﻿"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

EXPORT_FORMAT = "prosopo-gw/export"
EXPORT_VERSION = 1

_SQL_TYPES: Dict[ColumnType, str] = {
    "text": "TEXT",
    "int": "INTEGER",
    "real": "REAL",
    "bool": "INTEGER",
}
_TYPE_LABELS: Dict[ColumnType, str] = {
    "text": "texte",
    "int": "entier",
    "real": "decimal",
    "bool": "booleen",
}

DICTIONNAIRE = TableSpec(
    "dictionnaire",
    (
        Column("table", "text", "Nom de la table."),
        Column("colonne", "text", "Nom de la colonne."),
        Column("type", "text", "Type : texte, entier, decimal ou booleen."),
        Column("description", "text", "Contenu de la colonne."),
    ),
)


def neutralize_formula(text: str) -> str:
    """Neutralise l'interprétation en formule d'un tableur (préfixe ``'``)."""
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _csv_cell(column: Column, value: Value) -> str:
    if value is None:
        return ""
    if column.type == "bool":
        return "oui" if value else "non"
    if column.type == "real" and isinstance(value, (int, float)):
        return f"{value:g}".replace(".", ",")
    if column.type == "int":
        return str(value)
    return neutralize_formula(str(value))


def table_to_csv(table: Table) -> str:
    """Une table en CSV : BOM, ``;``, en-tête puis une ligne par enregistrement."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    columns = table.spec.columns
    writer.writerow(table.spec.column_names)
    for row in table.rows:
        writer.writerow([_csv_cell(c, row.get(c.name)) for c in columns])
    return BOM + buffer.getvalue()


def tables_to_json(tables: Sequence[Table], base: str, generated_at: datetime) -> str:
    """Toutes les tables dans une enveloppe JSON versionnée, valeurs natives."""
    payload = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "base": base,
        "tables": {
            t.spec.name: [
                {n: row.get(n) for n in t.spec.column_names} for row in t.rows
            ]
            for t in tables
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _create_table(conn: sqlite3.Connection, spec: TableSpec) -> None:
    columns: List[str] = []
    for c in spec.columns:
        definition = f"{_quote(c.name)} {_SQL_TYPES[c.type]}"
        if c.name == spec.primary_key:
            definition += " PRIMARY KEY"
        columns.append(definition)
    conn.execute(f"CREATE TABLE {_quote(spec.name)} ({', '.join(columns)})")
    for c in spec.columns:
        if c.name.endswith("_id") and c.name != spec.primary_key:
            conn.execute(
                f"CREATE INDEX {_quote(f'idx_{spec.name}_{c.name}')} "
                f"ON {_quote(spec.name)} ({_quote(c.name)})"
            )


def _sql_value(column: Column, value: Value) -> Value:
    if column.type == "bool" and value is not None:
        return 1 if value else 0
    return value


def tables_to_sqlite(tables: Sequence[Table]) -> bytes:
    """Base SQLite (octets du fichier) : une table par ``Table``, clés et index."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.sqlite"
        conn = sqlite3.connect(str(path))
        try:
            for t in tables:
                spec = t.spec
                _create_table(conn, spec)
                placeholders = ", ".join("?" for _ in spec.columns)
                conn.executemany(
                    f"INSERT INTO {_quote(spec.name)} VALUES ({placeholders})",
                    [
                        [_sql_value(c, row.get(c.name)) for c in spec.columns]
                        for row in t.rows
                    ],
                )
            conn.commit()
        finally:
            conn.close()
        return path.read_bytes()


def dictionary_table(specs: Sequence[TableSpec]) -> Table:
    """Table ``dictionnaire`` : une ligne par colonne de chaque table."""
    return Table(
        DICTIONNAIRE,
        [
            {
                "table": spec.name,
                "colonne": c.name,
                "type": _TYPE_LABELS[c.type],
                "description": c.description,
            }
            for spec in specs
            for c in spec.columns
        ],
    )
