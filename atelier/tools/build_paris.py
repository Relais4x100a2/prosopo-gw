"""Build the Paris street table (street key -> period -> arrondissement -> quartier).

Offline tool, run by hand: ``fetch`` downloads the public sources, ``build``
turns them into the gzip-compressed ``;``-separated tables shipped with the
atelier (see ``docs`` of the Paris table for the ODbL licence and attribution).

Sources and the fields read (checked on the layer metadata, ``?f=json``, on
2026-11-08):

* Vasserot quartiers, ALPAGE ArcGIS layer ``VasserotQuartiers_1790to1860``
  (``FeatureServer/1``, polygons, 48 objects, ``maxRecordCount`` 2000):
  ``ID_ALPAGE`` (quartier identifier, e.g. ``QU34``), ``NOM`` (quartier name),
  ``NUM_ARROND`` (number 1-12 of the pre-1860 arrondissement), ``NUM_QUARTI``.
* Vasserot roads, layer ``VasserotRoads_1810to1836`` (``FeatureServer/1``,
  polylines, 4 368 segments): ``NOM_ENTIER`` (full street name, e.g.
  ``Rue du Cloitre Notre Dame``), also ``NOM``, ``TYPE``, ``ID_ALPAGE``.
  The ``f=geojson`` output is in WGS84, quartiers and roads alike.
* Paris open data ``denominations-emprises-voies-actuelles`` (export JSON):
  ``typo_min`` (street name), ``arrdt`` (list such as ``["11e"]``), ``quartier``
  (list of quartier names).
* Paris open data ``denominations-des-voies-caduques`` (export JSON):
  ``typo_min``, ``arrdt`` (text, may be null), ``quartier`` (text),
  ``date_arret`` (``YYYY-MM-DD`` or null).

Rules: a Vasserot segment belongs to the quartier that contains its midpoint
(outside every quartier: dropped and counted). A current or defunct street
gives one row per arrondissement and quartier; a defunct street ended before
1860 is ignored. Open data gives quartier names without their arrondissement:
a name seen with a single arrondissement is tied to it, and a multi-arrondissement
record only keeps the pairs that are known this way. Keys come from
``prosopo_gw_atelier.places.streets.street_key``; a key ``rue faubourg ...`` is
also written without its leading ``rue``.

Example (from the repository root)::

    uv run --package prosopo-gw-atelier python atelier/tools/build_paris.py \\
        --output atelier/src/prosopo_gw_atelier/refdata/paris
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ATELIER_DIR = Path(__file__).resolve().parents[1]

if str(ATELIER_DIR / "src") not in sys.path:  # pragma: no cover - direct run
    sys.path.insert(0, str(ATELIER_DIR / "src"))

from prosopo_gw_atelier.places.streets import street_key  # noqa: E402
from prosopo_gw_atelier.refdata import normalize  # noqa: E402
from prosopo_gw_atelier.refdata.arrondissements import current, former_paris  # noqa: E402

_ARCGIS = "https://services.arcgis.com/ak2bo87wLfUpMrt1/ArcGIS/rest/services"
_OPEN_DATA = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
QUARTIERS_URL = (
    f"{_ARCGIS}/VasserotQuartiers_1790to1860/FeatureServer/1/query"
    "?where=1%3D1&outFields=*&f=geojson"
)
ROADS_URL = (
    f"{_ARCGIS}/VasserotRoads_1810to1836/FeatureServer/1/query"
    "?where=1%3D1&outFields=*&f=geojson"
)
ACTUELLES_URL = f"{_OPEN_DATA}/denominations-emprises-voies-actuelles/exports/json"
CADUQUES_URL = f"{_OPEN_DATA}/denominations-des-voies-caduques/exports/json"
SOURCE_URLS = (QUARTIERS_URL, ROADS_URL, ACTUELLES_URL, CADUQUES_URL)

USER_AGENT = "prosopo-gw-atelier build_paris"
PAGE_SIZE = 1000
PAGE_DELAY = 1.0

OLD = "paris-1795"
NEW = "paris-1860"
CUTOFF_YEAR = 1860

# Communes annexed to Paris on 1 January 1860 and their host arrondissement(s)
# (numbers of the 1860 arrondissements).
ANNEXED: dict[str, tuple[int, ...]] = {
    "Auteuil": (16,),
    "Passy": (16,),
    "Batignolles-Monceau": (17,),
    "Montmartre": (18,),
    "La Chapelle": (18,),
    "La Villette": (19,),
    "Belleville": (19, 20),
    "Charonne": (20,),
    "Bercy": (12,),
    "Vaugirard": (15,),
    "Grenelle": (15,),
}

Point = tuple[float, float]
Ring = list[Point]


@dataclass(frozen=True, order=True)
class Row:
    """One line of ``rues.csv.gz``."""

    key: str
    period: str
    arrondissement_id: str
    quartier_id: str
    quartier: str


@dataclass
class ParisTable:
    rows: set[Row] = field(default_factory=set)
    # (id, name, arrondissement_id, period)
    quartiers: set[tuple[str, str, str, str]] = field(default_factory=set)
    dropped_segments: int = 0
    skipped_streets: int = 0


def point_in_polygon(x: float, y: float, rings: list[list[Point]]) -> bool:
    """Even-odd rule over all rings: the first is the outline, others are holes."""
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def midpoint(line: list[Point]) -> Point:
    """Point at half of the length of a polyline."""
    if not line:
        raise ValueError("empty line")
    lengths = [
        ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        for (ax, ay), (bx, by) in zip(line, line[1:], strict=False)
    ]
    total = sum(lengths)
    if total == 0:
        return line[0]
    remaining = total / 2
    for (ax, ay), (bx, by), length in zip(line, line[1:], lengths, strict=False):
        if length and remaining <= length:
            t = remaining / length
            return (ax + (bx - ax) * t, ay + (by - ay) * t)
        remaining -= length
    return line[-1]  # pragma: no cover - rounding


def _points(coords: Iterable[Sequence[float]]) -> Ring:
    return [(float(c[0]), float(c[1])) for c in coords]


def _polygons(geometry: dict[str, Any]) -> list[list[Ring]]:
    if geometry["type"] == "Polygon":
        return [[_points(r) for r in geometry["coordinates"]]]
    if geometry["type"] == "MultiPolygon":
        return [[_points(r) for r in poly] for poly in geometry["coordinates"]]
    return []


def _lines(geometry: dict[str, Any]) -> list[Ring]:
    if geometry["type"] == "LineString":
        return [_points(geometry["coordinates"])]
    if geometry["type"] == "MultiLineString":
        return [_points(line) for line in geometry["coordinates"]]
    return []


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _add_street(
    table: ParisTable, name: str, period: str, arr: str, qid: str, qname: str
) -> None:
    key = street_key(name)
    if not key:
        table.skipped_streets += 1
        return
    keys = [key]
    if key.startswith("rue faubourg"):
        keys.append(key[len("rue ") :])
    for k in keys:
        table.rows.add(Row(k, period, arr, qid, qname))


def _vasserot(sources: Path, table: ParisTable) -> None:
    quartiers: list[tuple[str, str, str, list[list[Ring]]]] = []
    for feature in _read_json(sources / "vasserot_quartiers.geojson")["features"]:
        props = feature["properties"]
        former = former_paris(int(props["NUM_ARROND"]))
        if former is None:
            raise ValueError(f"unknown old arrondissement: {props['NUM_ARROND']!r}")
        qid, nom = str(props["ID_ALPAGE"]), str(props["NOM"])
        quartiers.append((qid, nom, former.id, _polygons(feature["geometry"])))
        table.quartiers.add((qid, nom, former.id, OLD))
    for feature in _read_json(sources / "vasserot_roads.geojson")["features"]:
        name = feature["properties"].get("NOM_ENTIER") or feature["properties"].get(
            "NOM"
        )
        for line in _lines(feature["geometry"]):
            if not line or not name:
                table.dropped_segments += 1
                continue
            x, y = midpoint(line)
            for qid, nom, arr, polygons in quartiers:
                if any(point_in_polygon(x, y, rings) for rings in polygons):
                    _add_street(table, name, OLD, arr, qid, nom)
                    break
            else:
                table.dropped_segments += 1


_ARRDT = re.compile(r"(\d+)\s*(?:er|e|ème|eme)\b", re.IGNORECASE)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # The defunct streets dataset joins several names in one text ("A, B").
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(v) for v in value]


def _arrondissements(value: Any) -> list[str]:
    ids: list[str] = []
    for text in _as_list(value):
        for number in _ARRDT.findall(text):
            arr = current("paris", int(number))
            if arr is not None and arr.id not in ids:
                ids.append(arr.id)
    return ids


def _quartier_id(name: str) -> str:
    return "paris-q-" + normalize(name).replace(" ", "-")


def _open_data(sources: Path, table: ParisTable) -> None:
    records: list[tuple[str, list[str], list[str]]] = []
    for record in _read_json(sources / "voies_actuelles.json"):
        records.append(
            (
                record["typo_min"],
                _arrondissements(record.get("arrdt")),
                _as_list(record.get("quartier")),
            )
        )
    for record in _read_json(sources / "voies_caduques.json"):
        stopped = str(record.get("date_arret") or "")
        if stopped[:4].isdigit() and int(stopped[:4]) < CUTOFF_YEAR:
            continue
        records.append(
            (
                record["typo_min"],
                _arrondissements(record.get("arrdt")),
                _as_list(record.get("quartier")),
            )
        )
    # Quartier -> arrondissements, from records that name a single arrondissement.
    known: dict[str, set[str]] = {}
    for _, arrs, qnames in records:
        if len(arrs) == 1:
            for q in qnames:
                known.setdefault(q, set()).add(arrs[0])
    for name, arrs, qnames in records:
        if not arrs:
            table.skipped_streets += 1
            continue
        pairs: list[tuple[str, str]] = []
        for arr in arrs:
            if not qnames:
                pairs.append((arr, ""))
            for q in qnames:
                if q not in known or arr in known[q]:
                    pairs.append((arr, q))
        for arr, q in pairs:
            qid = _quartier_id(q) if q else ""
            _add_street(table, name, NEW, arr, qid, q)
            if q:
                table.quartiers.add((qid, q, arr, NEW))


def _verify_annexed() -> None:
    if len(ANNEXED) != 11:
        raise ValueError("expected 11 communes annexed in 1860")
    for name, numbers in ANNEXED.items():
        for number in numbers:
            if current("paris", number) is None:
                raise ValueError(f"{name}: no arrondissement {number}")


def build_tables(sources: Path) -> ParisTable:
    """Read the four source files of ``sources`` into the street table."""
    table = ParisTable()
    _vasserot(sources, table)
    _open_data(sources, table)
    return table


def _write_gz_csv(
    path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]
) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(buffer.getvalue().encode("utf-8"))


def build(sources: Path, output: Path, extracted: date) -> None:
    """Write the tables of ``output`` from the source files of ``sources``."""
    _verify_annexed()
    table = build_tables(sources)
    output.mkdir(parents=True, exist_ok=True)
    _write_gz_csv(
        output / "rues.csv.gz",
        ("cle", "periode", "arrondissement_id", "quartier_id", "quartier"),
        (
            (r.key, r.period, r.arrondissement_id, r.quartier_id, r.quartier)
            for r in sorted(table.rows)
        ),
    )
    _write_gz_csv(
        output / "quartiers.csv.gz",
        ("id", "nom", "arrondissement_id", "periode"),
        sorted(table.quartiers),
    )
    _write_gz_csv(
        output / "communes_annexees.csv.gz",
        ("nom", "arrondissement_ids"),
        (
            (name, "|".join(c.id for n in nums if (c := current("paris", n))))
            for name, nums in sorted(ANNEXED.items())
        ),
    )
    lines = [
        f"extraction={extracted.isoformat()}",
        *(f"source={u}" for u in SOURCE_URLS),
    ]
    (output / "VERSION").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"{len(table.rows)} rows, {len(table.quartiers)} quartiers, "
        f"{table.dropped_segments} Vasserot segments outside every quartier, "
        f"{table.skipped_streets} streets without key or arrondissement"
    )


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        data: bytes = response.read()
    return data


def _fetch_arcgis(url: str, target: Path) -> None:
    features: list[Any] = []
    offset = 0
    while True:
        page = json.loads(
            _get(f"{url}&resultOffset={offset}&resultRecordCount={PAGE_SIZE}")
        )
        batch = page.get("features", [])
        features.extend(batch)
        if not batch or not page.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(batch)
        time.sleep(PAGE_DELAY)
    target.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def fetch(output: Path) -> None:
    """Download the four sources into ``output`` (network access)."""
    output.mkdir(parents=True, exist_ok=True)
    _fetch_arcgis(QUARTIERS_URL, output / "vasserot_quartiers.geojson")
    time.sleep(PAGE_DELAY)
    _fetch_arcgis(ROADS_URL, output / "vasserot_roads.geojson")
    time.sleep(PAGE_DELAY)
    (output / "voies_actuelles.json").write_bytes(_get(ACTUELLES_URL))
    time.sleep(PAGE_DELAY)
    (output / "voies_caduques.json").write_bytes(_get(CADUQUES_URL))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else ""
    )
    parser.add_argument("--output", type=Path, required=True, help="output folder")
    parser.add_argument(
        "--sources",
        type=Path,
        help="folder of already downloaded sources (skips the download)",
    )
    args = parser.parse_args(argv)
    if args.sources is not None:
        build(args.sources, args.output, date.today())
    else:
        with tempfile.TemporaryDirectory(prefix="build_paris_") as tmp:
            fetch(Path(tmp))
            build(Path(tmp), args.output, date.today())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
