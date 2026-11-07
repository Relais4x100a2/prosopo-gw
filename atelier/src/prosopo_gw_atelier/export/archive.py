"""The atelier's export archive (design § 9).

Layout, in this order: ``LISEZMOI.txt``, ``dictionnaire.csv``, one
``<table>.csv`` per pivot table (pivot order), ``<base>.json`` and
``<base>.sqlite``, where ``<base>`` is the ``.gw`` file stem (made ASCII-safe
by ``core``'s ``base_stem``). No ``*.org.json``: organisations are ``core``'s.

The archive is deterministic: every entry carries the same timestamp, taken
from ``generated_at``, and fixed attributes, so the same inputs give the same
bytes.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from importlib.resources import files

from geneweb_py.formats.table_writers import (
    base_stem,
    dictionary_table,
    table_to_csv,
    tables_to_json,
    tables_to_sqlite,
)

from ..project import Project
from ..refdata import RefData
from ..store.registry import PlaceRegistry
from .pivot import build_pivot

_FILE_MODE = 0o644 << 16


def readme(gw_name: str, base: str, ref: RefData, generated_at: datetime) -> str:
    """The ``LISEZMOI.txt`` of the archive."""
    template = files(__package__).joinpath("LISEZMOI.txt").read_text("utf-8")
    return template.format(
        gw=gw_name,
        base=base,
        date=generated_at.date().isoformat(),
        cog=ref.cog_vintage,
        postal=ref.postal_vintage,
    )


def build_archive(
    project: Project,
    registry: PlaceRegistry,
    ref: RefData,
    generated_at: datetime,
) -> bytes:
    """Zip of the pivot of ``project``: README, dictionary, CSV, JSON, SQLite."""
    tables = build_pivot(project.tables, registry)
    base = base_stem(project.gw_path.name)
    entries: list[tuple[str, bytes]] = [
        (
            "LISEZMOI.txt",
            readme(project.gw_path.name, base, ref, generated_at).encode("utf-8"),
        ),
        (
            "dictionnaire.csv",
            table_to_csv(dictionary_table([t.spec for t in tables])).encode("utf-8"),
        ),
        *((f"{t.spec.name}.csv", table_to_csv(t).encode("utf-8")) for t in tables),
        (f"{base}.json", tables_to_json(tables, base, generated_at).encode("utf-8")),
        (f"{base}.sqlite", tables_to_sqlite(tables)),
    ]
    stamp = generated_at.timetuple()[:6]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _FILE_MODE
            archive.writestr(info, data)
    return buffer.getvalue()
