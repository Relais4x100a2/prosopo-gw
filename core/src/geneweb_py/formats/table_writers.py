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
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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


README_TEMPLATE = """Export prosopo-gw — base « {base} », {date}

Ce dossier contient des données personnelles issues de votre base généalogique.
Ne le publiez pas et ne le versionnez pas.

base.org.json      Mon travail : organisations retenues, liens et mots ignorés.
base.sqlite        Toutes les tables, pour SQL, pandas ou DB Browser for SQLite.
base.json          Toutes les tables, pour un script, Streamlit ou un LLM.
csv/               Une table par fichier, pour un tableur (UTF-8, séparateur « ; »).
dictionnaire.csv   Description de chaque colonne de chaque table.

Les identifiants (personne_id, famille_id, evenement_id…) relient les tables entre elles.
Ils sont stables pour un même fichier .gw, pas d'une version de la base à l'autre.
"""


def base_stem(source_name: Optional[str]) -> str:
    """Nom court de la base : radical du fichier, caractères sûrs, ``base`` à défaut."""
    stem = Path(source_name).stem if source_name else ""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
    return safe or "base"


def archive_name(source_name: Optional[str], day: date) -> str:
    """``prosopo-<base>-<AAAA-MM-JJ>.zip``."""
    return f"prosopo-{base_stem(source_name)}-{day.isoformat()}.zip"


def build_zip(
    tables: Sequence[Table],
    companion: Dict[str, Any],
    base: str,
    generated_at: datetime,
) -> bytes:
    """Archive de l'export : LISEZMOI, dictionnaire, compagnon, SQLite, JSON, CSV."""
    buffer = io.BytesIO()
    readme = README_TEMPLATE.format(base=base, date=generated_at.date().isoformat())
    dictionary = dictionary_table([t.spec for t in tables])
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("LISEZMOI.txt", readme.encode("utf-8"))
        archive.writestr("dictionnaire.csv", table_to_csv(dictionary).encode("utf-8"))
        archive.writestr(
            "base.org.json",
            json.dumps(companion, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr("base.sqlite", tables_to_sqlite(tables))
        archive.writestr(
            "base.json", tables_to_json(tables, base, generated_at).encode("utf-8")
        )
        for t in tables:
            archive.writestr(f"csv/{t.spec.name}.csv", table_to_csv(t).encode("utf-8"))
    return buffer.getvalue()
