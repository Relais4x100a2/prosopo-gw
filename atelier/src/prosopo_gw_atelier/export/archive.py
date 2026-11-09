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
import textwrap
import zipfile
from collections.abc import Mapping
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
from ..refdata.paris_table import ParisTable
from ..store.registry import PlaceRegistry
from .pivot import build_pivot

_FILE_MODE = 0o644 << 16

_DICOTOPO_ORIGIN = "dicotopo"
_DICOTOPO_NOTICE = """\

  DicoTopo (CTHS, École nationale des chartes), https://dicotopo.cths.fr/,
  sous licence CC BY-NC-ND 3.0 FR (attribution, pas d'utilisation commerciale,
  pas de modification). Des niveaux de niveaux_lieux (origine dicotopo) portent
  l'identifiant d'un article (P…) ; la colonne source en donne le lien. Le nom du
  niveau est celui que vous avez validé : les formes anciennes et les commentaires
  de DicoTopo ne sont pas exportés.{departments}"""

_GEONAMES_ORIGIN = "geonames"
_GEONAMES_NOTICE = """\

  GeoNames, https://www.geonames.org/, sous licence Creative Commons
  Attribution 4.0 (CC BY 4.0). Des niveaux de niveaux_lieux (origine geonames)
  portent l'identifiant GeoNames (geonameid) du lieu ; la colonne source donne
  la date des données. Le nom du niveau est celui que vous avez validé.{countries}"""


def readme(
    gw_name: str,
    base: str,
    ref: RefData,
    generated_at: datetime,
    paris: ParisTable,
    dicotopo: Mapping[str, str] | None = None,
    geonames: Mapping[str, str] | None = None,
) -> str:
    """The ``LISEZMOI.txt`` of the archive.

    ``dicotopo`` is ``None`` when no DicoTopo level is exported (the notice is
    then left out), else the downloaded departments with their download date.
    ``geonames`` works the same way with the indexed countries.
    """
    notice = ""
    if dicotopo is not None:
        listing = "".join(
            f"\n  Département {code} : téléchargé le {date}."
            for code, date in sorted(dicotopo.items())
        )
        notice = _DICOTOPO_NOTICE.format(departments=listing)
    geo_notice = ""
    if geonames is not None:
        listing = "".join(
            f"\n  Pays {code} : données du {date}."
            for code, date in sorted(geonames.items())
        )
        geo_notice = _GEONAMES_NOTICE.format(countries=listing)
    template = files(__package__).joinpath("LISEZMOI.txt").read_text("utf-8")
    return template.format(
        gw=gw_name,
        base=base,
        date=generated_at.date().isoformat(),
        cog=ref.cog_vintage,
        postal=ref.postal_vintage,
        paris_extraction=paris.extraction,
        paris_attribution=textwrap.indent(paris.attribution.strip(), "  "),
        dicotopo=notice,
        geonames=geo_notice,
    )


def build_archive(
    project: Project,
    registry: PlaceRegistry,
    ref: RefData,
    generated_at: datetime,
    dicotopo_departments: Mapping[str, str] | None = None,
    geonames_countries: Mapping[str, str] | None = None,
) -> bytes:
    """Zip of the pivot of ``project``: README, dictionary, CSV, JSON, SQLite.

    ``dicotopo_departments`` (code to download date, from the local index) is
    cited in the README when a DicoTopo level is exported; it needs no network.
    ``geonames_countries`` (country code to extraction date) is cited likewise
    when a GeoNames level is exported.
    """
    tables = build_pivot(project.tables, registry, project.precisions())
    origins = {
        row.get("origine")
        for t in tables
        if t.spec.name == "niveaux_lieux"
        for row in t.rows
    }
    used = _DICOTOPO_ORIGIN in origins
    geo_used = _GEONAMES_ORIGIN in origins
    base = base_stem(project.gw_path.name)
    entries: list[tuple[str, bytes]] = [
        (
            "LISEZMOI.txt",
            readme(
                project.gw_path.name,
                base,
                ref,
                generated_at,
                project.paris_table,
                dict(dicotopo_departments or {}) if used else None,
                dict(geonames_countries or {}) if geo_used else None,
            ).encode("utf-8"),
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
