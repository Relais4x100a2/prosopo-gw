"""Loader of the Paris street table shipped in ``refdata/paris`` (ODbL licence).

The table maps a street key (``places.streets.street_key``) and a period
(``paris-1795`` or ``paris-1860``) to the arrondissements and quartiers where
that street lies. It is built offline by ``atelier/tools/build_paris.py``.
"""

from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .normalize import normalize

DEFAULT_PARIS_DIR = Path(__file__).resolve().parent / "paris"
TABLE_FILES = ("rues.csv.gz", "quartiers.csv.gz", "communes_annexees.csv.gz")
VERSION_FILE = "VERSION"
ATTRIBUTION_FILE = "ATTRIBUTION.txt"


@dataclass(frozen=True)
class StreetHit:
    """One place where a street lies: an arrondissement, maybe a quartier."""

    arrondissement_id: str
    quartier_id: str | None
    quartier: str | None


class ParisTable:
    """Street lookups by key and period, plus the communes annexed in 1860."""

    def __init__(
        self,
        directory: Path,
        streets: dict[tuple[str, str], tuple[StreetHit, ...]],
        quartiers: dict[str, int],
        annexed: dict[str, tuple[str, ...]],
        extraction: str,
        attribution: str,
    ) -> None:
        self.directory = directory
        self._streets = streets
        self._quartiers = quartiers
        self._annexed = annexed
        self.extraction = extraction
        self.attribution = attribution

    def streets(self, key: str, period: str) -> tuple[StreetHit, ...]:
        """Return the places of the street ``key`` in ``period`` (empty if unknown)."""
        return self._streets.get((key, period), ())

    def annexed(self, name_key: str) -> tuple[str, ...]:
        """Return the arrondissement ids hosting an annexed commune (normalized)."""
        return self._annexed.get(name_key, ())

    def quartier_count(self, period: str) -> int:
        """Return the number of quartiers known for ``period``."""
        return self._quartiers.get(period, 0)


def _read_table(directory: Path, name: str) -> Iterator[dict[str, str]]:
    with gzip.open(directory / name, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle, delimiter=";")


def _extraction(directory: Path) -> str:
    text = (directory / VERSION_FILE).read_text(encoding="utf-8")
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "extraction":
            return value.strip()
    return ""


@lru_cache(maxsize=4)
def _load_cached(directory: Path) -> ParisTable:
    missing = [
        n
        for n in (*TABLE_FILES, VERSION_FILE, ATTRIBUTION_FILE)
        if not (directory / n).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"Table des rues de Paris absente ou incomplète dans {directory} "
            f"(manquant : {', '.join(missing)}). Elle se construit hors ligne "
            "avec atelier/tools/build_paris.py."
        )
    grouped: dict[tuple[str, str], list[StreetHit]] = defaultdict(list)
    for row in _read_table(directory, "rues.csv.gz"):
        grouped[(row["cle"], row["periode"])].append(
            StreetHit(
                row["arrondissement_id"],
                row["quartier_id"] or None,
                row["quartier"] or None,
            )
        )
    counts: dict[str, int] = defaultdict(int)
    for row in _read_table(directory, "quartiers.csv.gz"):
        counts[row["periode"]] += 1
    annexed = {
        normalize(row["nom"]): tuple(
            i for i in row["arrondissement_ids"].split("|") if i
        )
        for row in _read_table(directory, "communes_annexees.csv.gz")
    }
    return ParisTable(
        directory,
        {k: tuple(v) for k, v in grouped.items()},
        dict(counts),
        annexed,
        _extraction(directory),
        (directory / ATTRIBUTION_FILE).read_text(encoding="utf-8"),
    )


def load_paris_table(directory: Path | None = None) -> ParisTable:
    """Load (once per directory) the Paris street table.

    ``directory`` defaults to the table embedded in the package (``refdata/paris``).
    Raises ``FileNotFoundError`` when the table has not been built.
    """
    return _load_cached(
        (DEFAULT_PARIS_DIR if directory is None else directory).resolve()
    )
