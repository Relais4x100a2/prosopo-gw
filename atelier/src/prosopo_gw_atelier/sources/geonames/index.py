"""Reading of GeoNames per-country dumps and their local SQLite index.

GeoNames data is published under CC BY 4.0. Nothing of it is shipped here: the
user downloads ``<CC>.zip`` (one ``<CC>.txt`` inside) plus the common tables
``admin1CodesASCII.txt``, ``admin2Codes.txt`` and ``countryInfo.txt``.

``<CC>.txt`` is UTF-8, tab-separated, without header, 19 columns: geonameid,
name, asciiname, alternatenames (comma-separated), latitude, longitude, feature
class, feature code, country code, cc2, admin1, admin2, admin3, admin4,
population, elevation, dem, timezone, modification date. Only feature classes
``P`` (populated places) and ``A`` (administrative divisions) are kept.

The admin code tables map ``CC.admin1`` (and ``CC.admin1.admin2``) to
``name<TAB>asciiname<TAB>geonameid``.
"""

from __future__ import annotations

import io
import re
import sqlite3
import threading
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ...places.cluster import name_key
from ..base import SourceError

_COUNTRY = re.compile(r"^[A-Z]{2}$")
_KEPT_CLASSES = frozenset("PA")
_COLUMNS = 19
_BATCH = 10_000
_BUSY_TIMEOUT = 30.0
_URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|www\.)", re.IGNORECASE)


@dataclass(frozen=True)
class GeoPlace:
    """One GeoNames place (populated place or administrative division)."""

    geonameid: int
    name: str
    feature_class: str
    feature_code: str
    country: str
    admin1: str
    admin2: str
    population: int
    latitude: float
    longitude: float


def check_country(country: str) -> str:
    """Return ``country`` if it is two ASCII uppercase letters, else raise."""
    if not _COUNTRY.fullmatch(country):
        raise SourceError(f"Code pays GeoNames invalide : {country!r}.")
    return country


def _open_member(archive: zipfile.ZipFile, country: str) -> io.TextIOWrapper:
    member = f"{country}.txt"
    for info in archive.infolist():
        name = info.filename
        if "/" in name or "\\" in name or ".." in name:
            continue  # only a plain <CC>.txt at the root is read
        if name == member:
            return io.TextIOWrapper(archive.open(info), encoding="utf-8", newline="")
    raise SourceError(f"Le fichier {member} est absent de l'archive GeoNames.")


def _rows(zip_path: Path, country: str) -> Iterator[list[str]]:
    check_country(country)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            with _open_member(archive, country) as text:
                for line in text:
                    fields = line.rstrip("\r\n").split("\t")
                    if len(fields) >= _COLUMNS:
                        yield fields
    except zipfile.BadZipFile as error:
        raise SourceError(f"Archive GeoNames illisible : {zip_path.name}.") from error


def _int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return 0


def _float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


def read_dump(zip_path: Path, country: str) -> Iterator[GeoPlace]:
    """Yield the ``P`` and ``A`` places of ``<CC>.zip``, line by line."""
    for f in _rows(zip_path, country):
        if f[6] not in _KEPT_CLASSES or not f[0].isdigit() or not f[1].strip():
            continue
        yield GeoPlace(
            int(f[0]),
            f[1].strip(),
            f[6],
            f[7],
            f[8] or country,
            f[10],
            f[11],
            _int(f[14]),
            _float(f[4]),
            _float(f[5]),
        )


def useful_alternate(name: str) -> bool:
    """Whether an alternate name is a real name (not a code, a number or a URL)."""
    name = name.strip()
    if len(name) < 2 or _URL.match(name):
        return False
    if any(c.isdigit() for c in name):
        return False  # postal codes, IATA-like codes with digits, ids
    return any(c.isalpha() for c in name)


def read_names(zip_path: Path, country: str) -> Iterator[tuple[int, str]]:
    """Yield ``(geonameid, name)`` of the useful alternate names (``P``/``A``)."""
    for f in _rows(zip_path, country):
        if f[6] not in _KEPT_CLASSES or not f[0].isdigit():
            continue
        geonameid = int(f[0])
        for alternate in (f[2], *f[3].split(",")):
            if useful_alternate(alternate):
                yield geonameid, alternate.strip()


def _keyed_names(zip_path: Path, country: str) -> Iterator[tuple[str, int]]:
    """``(name_key, geonameid)`` of the name, asciiname and useful alternates.

    Identical keys of one place are emitted once.
    """
    for f in _rows(zip_path, country):
        if f[6] not in _KEPT_CLASSES or not f[0].isdigit() or not f[1].strip():
            continue
        geonameid = int(f[0])
        keys = {name_key(f[1])}
        for alternate in (f[2], *f[3].split(",")):
            if useful_alternate(alternate):
                keys.add(name_key(alternate))
        keys.discard("")
        for key in sorted(keys):
            yield key, geonameid


def read_admin_codes(path: Path) -> dict[str, tuple[str, int]]:
    """``admin1CodesASCII.txt`` / ``admin2Codes.txt``: key → ``(name, geonameid)``."""
    codes: dict[str, tuple[str, int]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for line in handle:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 2 or not fields[0] or fields[0].startswith("#"):
                continue
            codes[fields[0]] = (fields[1], _int(fields[3]) if len(fields) > 3 else 0)
    return codes


def read_country_info(path: Path) -> dict[str, str]:
    """``countryInfo.txt``: ISO code → English country name."""
    countries: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) > 4 and _COUNTRY.fullmatch(fields[0]) and fields[4]:
                countries[fields[0]] = fields[4]
    return countries


_SCHEMA = """
CREATE TABLE places (
    geonameid INTEGER PRIMARY KEY, name TEXT NOT NULL, feature_class TEXT NOT NULL,
    feature_code TEXT NOT NULL, country TEXT NOT NULL, admin1 TEXT NOT NULL,
    admin2 TEXT NOT NULL, population INTEGER NOT NULL,
    latitude REAL NOT NULL, longitude REAL NOT NULL
);
CREATE TABLE names (key TEXT NOT NULL, geonameid INTEGER NOT NULL);
CREATE TABLE admin (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, geonameid INTEGER NOT NULL
);
CREATE TABLE meta (extracted TEXT NOT NULL);
"""
_SELECT = (
    "SELECT geonameid, name, feature_class, feature_code, country, admin1, admin2, "
    "population, latitude, longitude FROM places"
)


def _place(row: tuple[object, ...]) -> GeoPlace:
    return GeoPlace(*row)  # type: ignore[arg-type]


def _chunks(items: Iterable[tuple[object, ...]]) -> Iterator[list[tuple[object, ...]]]:
    batch: list[tuple[object, ...]] = []
    for item in items:
        batch.append(item)
        if len(batch) >= _BATCH:
            yield batch
            batch = []
    if batch:
        yield batch


class GeoNamesIndex:
    """One SQLite file per country (``<CC>.sqlite``) in ``directory``."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        self._countries: dict[str, str] | None = None
        directory.mkdir(parents=True, exist_ok=True)

    def _file(self, country: str) -> Path:
        return self._directory / f"{check_country(country)}.sqlite"

    def _connect(self, path: Path) -> sqlite3.Connection:
        """Writer connection (creates the file: only used on ``.part`` files)."""
        return sqlite3.connect(path, timeout=_BUSY_TIMEOUT)

    def _connect_ro(self, path: Path) -> sqlite3.Connection:
        """Reader connection: never creates a file (fails if it is missing)."""
        return sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, timeout=_BUSY_TIMEOUT
        )

    def _invalidate(self) -> None:
        with self._lock:
            self._countries = None

    def build(
        self, country: str, zip_path: Path, admin1: Path, admin2: Path, extracted: str
    ) -> int:
        """(Re)build the index of ``country`` atomically; return the place count."""
        target = self._file(country)
        part = target.with_name(target.name + ".part")
        for leftover in (part, Path(f"{part}-journal")):
            leftover.unlink(missing_ok=True)
        prefix = f"{country}."
        admin_rows = [
            (code, name, geonameid)
            for table in (read_admin_codes(admin1), read_admin_codes(admin2))
            for code, (name, geonameid) in table.items()
            if code.startswith(prefix)
        ]
        count = 0
        db = self._connect(part)
        try:
            try:
                db.executescript(_SCHEMA)
                with db:
                    seen: set[int] = set()
                    for batch in _chunks(
                        (
                            p.geonameid,
                            p.name,
                            p.feature_class,
                            p.feature_code,
                            p.country,
                            p.admin1,
                            p.admin2,
                            p.population,
                            p.latitude,
                            p.longitude,
                        )
                        for p in _unique(read_dump(zip_path, country), seen)
                    ):
                        db.executemany(
                            "INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?)", batch
                        )
                        count += len(batch)
                    for batch in _chunks(
                        (key, gid)
                        for key, gid in _keyed_names(zip_path, country)
                        if gid in seen
                    ):
                        db.executemany("INSERT INTO names VALUES (?, ?)", batch)
                    db.executemany("INSERT INTO admin VALUES (?, ?, ?)", admin_rows)
                    db.execute("INSERT INTO meta VALUES (?)", (extracted,))
                    db.execute("CREATE INDEX names_key ON names (key)")
            finally:
                db.close()
            part.replace(target)
        except BaseException:
            for leftover in (part, Path(f"{part}-journal")):
                leftover.unlink(missing_ok=True)
            raise
        self._invalidate()
        return count

    def countries(self) -> dict[str, str]:
        """Indexed countries with their extraction date."""
        with self._lock:
            if self._countries is not None:
                return dict(self._countries)
        found: dict[str, str] = {}
        for path in sorted(self._directory.glob("??.sqlite")):
            country = path.stem
            if not _COUNTRY.fullmatch(country):
                continue
            try:
                db = self._connect_ro(path)
                try:
                    row = db.execute("SELECT extracted FROM meta").fetchone()
                finally:
                    db.close()
            except sqlite3.Error:
                continue
            if row:
                found[country] = str(row[0])
        with self._lock:
            self._countries = found
        return dict(found)

    def _query(
        self, country: str, sql: str, params: tuple[object, ...] = ()
    ) -> list[tuple[object, ...]]:
        path = self._file(country)
        try:
            db = self._connect_ro(path)
        except sqlite3.Error:
            return []
        try:
            return db.execute(sql, params).fetchall()
        except sqlite3.Error:
            return []
        finally:
            db.close()

    def lookup(self, country: str, key: str) -> list[GeoPlace]:
        """Places whose name or useful alternate name has this ``name_key``."""
        rows = self._query(
            country,
            f"{_SELECT} WHERE geonameid IN (SELECT geonameid FROM names WHERE key = ?) "
            "ORDER BY population DESC, geonameid",
            (key,),
        )
        return [_place(row) for row in rows]

    def get(self, country: str, geonameid: int) -> GeoPlace | None:
        rows = self._query(country, f"{_SELECT} WHERE geonameid = ?", (geonameid,))
        return _place(rows[0]) if rows else None

    def admin_name(
        self, country: str, admin1: str, admin2: str | None = None
    ) -> tuple[str, int] | None:
        """``(name, geonameid)`` of a first- or second-level division, if known."""
        code = f"{country}.{admin1}" + (f".{admin2}" if admin2 else "")
        rows = self._query(
            country, "SELECT name, geonameid FROM admin WHERE code = ?", (code,)
        )
        return (str(rows[0][0]), int(str(rows[0][1]))) if rows else None

    def remove(self, country: str) -> None:
        target = self._file(country)
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        self._invalidate()


def _unique(places: Iterator[GeoPlace], seen: set[int]) -> Iterator[GeoPlace]:
    for place in places:
        if place.geonameid in seen:
            continue
        seen.add(place.geonameid)
        yield place
