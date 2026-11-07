"""Loading of the embedded reference data (INSEE COG and La Poste postal codes).

The data directory holds one gzip-compressed, ``;``-separated UTF-8 CSV file per
table, plus a ``VERSION`` file. It is produced by ``atelier/tools/build_refdata.py``.

- ``communes.csv.gz``: ``insee;nom;departement;region`` (department and region
  codes) for current communes only.
- ``historique.csv.gz``: ``ancien_nom;insee_actuel;date_effet``: former names and
  merged communes, with the current commune they now belong to.
- ``departements.csv.gz``: ``code;nom;region``.
- ``regions.csv.gz``: ``code;nom;avant_2016`` (``1`` for a pre-2016 region).
- ``pays.csv.gz``: ``nom;nom_officiel``.
- ``codes_postaux.csv.gz``: ``code_postal;insee``.
- ``VERSION``: ``cog=<vintage>`` and ``postal=<vintage>`` lines.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .normalize import normalize

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"

TABLE_FILES = (
    "communes.csv.gz",
    "historique.csv.gz",
    "departements.csv.gz",
    "regions.csv.gz",
    "pays.csv.gz",
    "codes_postaux.csv.gz",
)
VERSION_FILE = "VERSION"

_DEPARTMENT_CODE = re.compile(r"^(?:\d{1,3}|2[ab])$", re.IGNORECASE)


@dataclass(frozen=True)
class Commune:
    """A current commune of the COG."""

    insee: str
    name: str
    department: str
    region: str


@dataclass(frozen=True)
class NameMatch:
    """A commune found by name.

    ``former_name`` is set when the name is a former name of the commune or the
    name of a commune merged into it.
    """

    commune: Commune
    former_name: str | None


class RefData:
    """Indexed reference data: communes, departments, regions, countries."""

    def __init__(
        self,
        *,
        cog_vintage: str,
        postal_vintage: str,
        communes: list[Commune],
        former_names: list[tuple[str, str]],
        departments: list[tuple[str, str]],
        regions: list[tuple[str, bool]],
        countries: list[tuple[str, str]],
        postal_codes: list[tuple[str, str]],
    ) -> None:
        self.cog_vintage = cog_vintage
        self.postal_vintage = postal_vintage

        self._by_insee: dict[str, Commune] = {c.insee: c for c in communes}
        self._by_name: dict[str, list[Commune]] = defaultdict(list)
        for commune in communes:
            self._by_name[normalize(commune.name)].append(commune)
        self._former: dict[str, list[tuple[Commune, str]]] = defaultdict(list)
        for former_name, insee in former_names:
            current = self._by_insee.get(insee)
            if current is not None:
                self._former[normalize(former_name)].append((current, former_name))

        self._postal: dict[str, list[Commune]] = defaultdict(list)
        for postal_code, insee in postal_codes:
            current = self._by_insee.get(insee)
            if current is not None and current not in self._postal[postal_code]:
                self._postal[postal_code].append(current)
        for postal_communes in self._postal.values():
            postal_communes.sort(key=lambda c: c.insee)

        self._department_codes = {code.upper() for code, _ in departments}
        self._department_by_name = {normalize(name): code for code, name in departments}

        self._region_by_name: dict[str, tuple[str, bool]] = {}
        # Current regions first: a name shared by both lists is a current region.
        for name, before_2016 in sorted(regions, key=lambda r: r[1]):
            self._region_by_name.setdefault(normalize(name), (name, before_2016))

        self._country_by_name: dict[str, str] = {}
        for name, _ in countries:
            self._country_by_name.setdefault(normalize(name), name)
        for name, official_name in countries:
            if official_name:
                self._country_by_name.setdefault(normalize(official_name), name)

    @property
    def commune_count(self) -> int:
        """Number of current communes."""
        return len(self._by_insee)

    def commune_by_insee(self, code: str) -> Commune | None:
        """Return the current commune with this INSEE code, if any."""
        return self._by_insee.get(code.strip().upper())

    def communes_by_name(self, name: str) -> list[NameMatch]:
        """Return the communes whose current or former name matches ``name``.

        Matching is done on normalized names. Current names come first; a
        commune matched by its current name is not repeated as a former name.
        """
        key = normalize(name)
        current = sorted(self._by_name.get(key, []), key=lambda c: c.insee)
        matches = [NameMatch(commune, None) for commune in current]
        seen = set(current)
        former = sorted(self._former.get(key, []), key=lambda f: f[0].insee)
        for commune, former_name in former:
            if commune not in seen:
                seen.add(commune)
                matches.append(NameMatch(commune, former_name))
        return matches

    def communes_by_postal(self, code: str) -> list[Commune]:
        """Return the communes served by a postal code, sorted by INSEE code."""
        return list(self._postal.get(code.strip(), []))

    def department(self, token: str) -> str | None:
        """Return a department code from its name, number or ``(number)``."""
        text = token.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()
        if _DEPARTMENT_CODE.match(text):
            code = text.upper()
            if code.isdigit() and len(code) == 1:
                code = f"0{code}"
            return code if code in self._department_codes else None
        return self._department_by_name.get(normalize(text))

    def region(self, token: str) -> tuple[str, bool] | None:
        """Return ``(canonical name, True if pre-2016 region)`` for a region name."""
        return self._region_by_name.get(normalize(token))

    def country(self, token: str) -> str | None:
        """Return the canonical name of a country from its usual or official name."""
        return self._country_by_name.get(normalize(token))


def _read_table(directory: Path, name: str) -> Iterator[dict[str, str]]:
    with gzip.open(directory / name, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle, delimiter=";")


def _read_version(directory: Path) -> dict[str, str]:
    text = (directory / VERSION_FILE).read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for line in io.StringIO(text):
        key, sep, value = line.strip().partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def _check_directory(directory: Path) -> None:
    missing = [
        name
        for name in (*TABLE_FILES, VERSION_FILE)
        if not (directory / name).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"Données de référence absentes ou incomplètes dans {directory} "
            f"(manquant : {', '.join(missing)}). Elles se construisent hors ligne "
            "avec atelier/tools/build_refdata.py (voir atelier/README.md)."
        )


@lru_cache(maxsize=8)
def _load_cached(directory: Path) -> RefData:
    _check_directory(directory)
    version = _read_version(directory)
    communes = [
        Commune(row["insee"], row["nom"], row["departement"], row["region"])
        for row in _read_table(directory, "communes.csv.gz")
    ]
    return RefData(
        cog_vintage=version.get("cog", ""),
        postal_vintage=version.get("postal", ""),
        communes=communes,
        former_names=[
            (row["ancien_nom"], row["insee_actuel"])
            for row in _read_table(directory, "historique.csv.gz")
        ],
        departments=[
            (row["code"], row["nom"])
            for row in _read_table(directory, "departements.csv.gz")
        ],
        regions=[
            (row["nom"], row["avant_2016"] == "1")
            for row in _read_table(directory, "regions.csv.gz")
        ],
        countries=[
            (row["nom"], row["nom_officiel"])
            for row in _read_table(directory, "pays.csv.gz")
        ],
        postal_codes=[
            (row["code_postal"], row["insee"])
            for row in _read_table(directory, "codes_postaux.csv.gz")
        ],
    )


def load_refdata(directory: Path | None = None) -> RefData:
    """Load (once per directory) the reference data.

    ``directory`` defaults to the data embedded in the package (``refdata/data``).
    Raises ``FileNotFoundError`` when the data has not been built.
    """
    target = DEFAULT_DATA_DIR if directory is None else directory
    return _load_cached(target.resolve())
