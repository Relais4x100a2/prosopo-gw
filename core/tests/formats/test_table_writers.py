"""Rendus CSV, JSON et SQLite des tables d'export. Fixtures 100 % synthétiques."""

import csv
import io
import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.formats.table_writers import (
    BOM,
    dictionary_table,
    table_to_csv,
    tables_to_json,
    tables_to_sqlite,
)
from geneweb_py.formats.tables import Column, Table, TableSpec, build_base_tables

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rich_pevt_wit.gw"
WHEN = datetime(2026, 1, 2, 3, 4, 5)

SPEC = TableSpec(
    "essai",
    (
        Column("essai_id", "text", "Identifiant."),
        Column("personne_id", "text", "Personne."),
        Column("nom", "text", "Nom."),
        Column("annee", "int", "Année."),
        Column("confiance", "real", "Confiance."),
        Column("actif", "bool", "Actif."),
    ),
    primary_key="essai_id",
)


def _table(**override: Any) -> Table:
    row: dict[str, Any] = {
        "essai_id": "e1",
        "personne_id": "DUPONT_Jean_0",
        "nom": "Atelier",
        "annee": 1870,
        "confiance": 0.8,
        "actif": True,
    }
    row.update(override)
    second = dict(row, essai_id="e2", actif=False, annee=None, confiance=None)
    return Table(SPEC, [row, second])


def _csv_rows(text: str) -> list[list[str]]:
    assert text.startswith(BOM)
    return list(csv.reader(io.StringIO(text[len(BOM) :]), delimiter=";"))


def _sqlite(tables: Sequence[Table], tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "export.sqlite"
    path.write_bytes(tables_to_sqlite(tables))
    return sqlite3.connect(str(path))


def _base_tables() -> list[Table]:
    return build_base_tables(GeneWebParser().parse_file(str(FIXTURE)))


def test_csv_conventions() -> None:
    text = table_to_csv(_table())
    assert text.startswith(BOM)
    header, first, second = _csv_rows(text)
    assert header == SPEC.column_names
    assert ";" in text.splitlines()[0]
    assert first == ["e1", "DUPONT_Jean_0", "Atelier", "1870", "0,8", "oui"]
    assert second == ["e2", "DUPONT_Jean_0", "Atelier", "", "", "non"]


def test_formula_only_neutralized_in_csv(tmp_path: Path) -> None:
    table = _table(nom="=SOMME(A1)")
    assert _csv_rows(table_to_csv(table))[1][2] == "'=SOMME(A1)"
    payload = json.loads(tables_to_json([table], "base", WHEN))
    assert payload["tables"]["essai"][0]["nom"] == "=SOMME(A1)"
    conn = _sqlite([table], tmp_path)
    assert conn.execute(
        'SELECT nom FROM "essai" WHERE essai_id = ?', ("e1",)
    ).fetchone() == ("=SOMME(A1)",)


def test_csv_round_trip_multiline() -> None:
    value = 'a;b\n"c"'
    rows = _csv_rows(table_to_csv(_table(nom=value)))
    assert len(rows) == 3
    assert rows[1][2] == value


def test_json_envelope_and_types() -> None:
    payload = json.loads(tables_to_json([_table()], "ma_base", WHEN))
    assert payload["format"] == "prosopo-gw/export"
    assert payload["version"] == 1
    assert payload["base"] == "ma_base"
    assert payload["generated_at"] == "2026-01-02T03:04:05"
    first, second = payload["tables"]["essai"]
    assert (
        first["actif"] is True and first["annee"] == 1870 and first["confiance"] == 0.8
    )
    assert second["annee"] is None and second["actif"] is False


def test_sqlite_tables_and_join(tmp_path: Path) -> None:
    tables = _base_tables()
    conn = _sqlite(tables, tmp_path)
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert names == {t.spec.name for t in tables}
    for t in tables:
        assert conn.execute(f'SELECT COUNT(*) FROM "{t.spec.name}"').fetchone() == (
            len(t.rows),
        )
    joined = conn.execute(
        "SELECT p.nom FROM temoins t JOIN personnes p ON p.personne_id = t.personne_id"
    ).fetchall()
    assert joined


def test_sqlite_primary_key_and_indexes(tmp_path: Path) -> None:
    conn = _sqlite([_table()], tmp_path)
    info = {r[1]: r for r in conn.execute('PRAGMA table_info("essai")')}
    assert info["essai_id"][5] == 1  # pk
    assert info["annee"][2] == "INTEGER" and info["confiance"][2] == "REAL"
    assert info["actif"][2] == "INTEGER" and info["nom"][2] == "TEXT"
    indexed = set()
    for idx in conn.execute('PRAGMA index_list("essai")'):
        for col in conn.execute(f'PRAGMA index_info("{idx[1]}")'):
            indexed.add(col[2])
    assert "personne_id" in indexed
    assert "nom" not in indexed
    assert conn.execute('SELECT actif FROM "essai" ORDER BY essai_id').fetchall() == [
        (1,),
        (0,),
    ]


def test_parity_across_formats(tmp_path: Path) -> None:
    tables = _base_tables() + [_table()]
    payload = json.loads(tables_to_json(tables, "base", WHEN))
    conn = _sqlite(tables, tmp_path)
    assert list(payload["tables"]) == [t.spec.name for t in tables]
    for t in tables:
        header, *rows = _csv_rows(table_to_csv(t))
        assert header == t.spec.column_names
        assert len(rows) == len(t.rows) == len(payload["tables"][t.spec.name])
        for row in payload["tables"][t.spec.name]:
            assert list(row) == t.spec.column_names
        columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{t.spec.name}")')]
        assert columns == t.spec.column_names


def test_dictionary_covers_every_column() -> None:
    specs = [t.spec for t in _base_tables()] + [SPEC]
    table = dictionary_table(specs)
    assert table.spec.name == "dictionnaire"
    assert table.spec.column_names == ["table", "colonne", "type", "description"]
    pairs = [(r["table"], r["colonne"]) for r in table.rows]
    assert pairs == [(s.name, c.name) for s in specs for c in s.columns]
    types = {r["colonne"]: r["type"] for r in table.rows if r["table"] == "essai"}
    assert types == {
        "essai_id": "texte",
        "personne_id": "texte",
        "nom": "texte",
        "annee": "entier",
        "confiance": "decimal",
        "actif": "booleen",
    }
    assert all(r["description"] for r in table.rows)


@pytest.mark.parametrize("value", ["Éléonore Œuvre"])
def test_unicode_survives_all_formats(value: str, tmp_path: Path) -> None:
    table = _table(nom=value)
    assert _csv_rows(table_to_csv(table))[1][2] == value
    assert (
        json.loads(tables_to_json([table], "base", WHEN))["tables"]["essai"][0]["nom"]
        == value
    )
    assert value in tables_to_json([table], "base", WHEN)
    conn = _sqlite([table], tmp_path)
    assert conn.execute(
        'SELECT nom FROM "essai" WHERE essai_id = ?', ("e1",)
    ).fetchone() == (value,)
