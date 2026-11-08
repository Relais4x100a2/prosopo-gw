"""Build the embedded reference data from the downloaded INSEE COG and La Poste files.

Offline tool, run by hand (no network access). It reads the source files given
on the command line, detects their encoding (UTF-8 or Windows-1252/Latin-1) and
delimiter (``,``, ``;`` or tab), matches headers case- and accent-insensitively,
and writes the gzip-compressed tables read by
``prosopo_gw_atelier.refdata.load_refdata`` (format described in
``refdata/loader.py``).

Example (from the repository root, see ``atelier/README.md``)::

    uv run --package prosopo-gw-atelier python atelier/tools/build_refdata.py \\
        --communes _local_testdata/refdata/cog-2026/v_commune_2026.csv ...
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ATELIER_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ATELIER_DIR / "src" / "prosopo_gw_atelier" / "refdata" / "data"

if str(ATELIER_DIR / "src") not in sys.path:  # pragma: no cover - direct run
    sys.path.insert(0, str(ATELIER_DIR / "src"))

from prosopo_gw_atelier.refdata.normalize import normalize  # noqa: E402

# Accepted header spellings for each logical column, compared after
# ``_header_key`` (case, accents, BOM, leading ``#`` and punctuation ignored).
# Fixing a header of a new release is a one-line change here.
COLUMNS: dict[str, tuple[str, ...]] = {
    # v_commune_<year>, v_commune_depuis_1943
    "TYPECOM": ("TYPECOM",),
    "COM": ("COM",),
    "DEP": ("DEP",),
    "REG": ("REG", "REGION"),
    "LIBELLE": ("LIBELLE",),
    "NCCENR": ("NCCENR",),
    "COMPARENT": ("COMPARENT",),
    "DATE_FIN": ("DATE_FIN",),
    # v_mvt_commune_<year>
    "MOD": ("MOD",),
    "DATE_EFF": ("DATE_EFF",),
    "TYPECOM_AV": ("TYPECOM_AV",),
    "COM_AV": ("COM_AV",),
    "LIBELLE_AV": ("LIBELLE_AV",),
    "TYPECOM_AP": ("TYPECOM_AP",),
    "COM_AP": ("COM_AP",),
    # v_pays_territoire_<year>
    "LIBCOG": ("LIBCOG",),
    "LIBENR": ("LIBENR",),
    # La Poste, base officielle des codes postaux (hexasmal)
    "CODE_COMMUNE_INSEE": ("CODE_COMMUNE_INSEE",),
    "CODE_POSTAL": ("CODE_POSTAL",),
    "LIBELLE_D_ACHEMINEMENT": ("LIBELLE_D_ACHEMINEMENT",),
}

# Region names: the 2026 files have LIBELLE, the 2015 file only NCCENR.
REGION_NAME_COLUMNS = ("LIBELLE", "NCCENR")


class SourceFormatError(ValueError):
    """A source file does not have the expected layout."""


def _header_key(header: str) -> str:
    text = header.replace("﻿", "").strip().lstrip("#").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    chars = [c if c.isalnum() else "_" for c in text.upper()]
    return "_".join(part for part in "".join(chars).split("_") if part)


def _decode(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def _detect_delimiter(header_line: str, path: Path) -> str:
    counts = {d: header_line.count(d) for d in (";", ",", "\t")}
    delimiter = max(counts, key=lambda d: counts[d])
    if counts[delimiter] == 0:
        raise SourceFormatError(
            f"{path.name} : séparateur introuvable dans la ligne d'en-tête "
            f"({header_line[:80]!r})."
        )
    return delimiter


@dataclass
class SourceTable:
    """A source CSV file read in memory, with tolerant column lookup."""

    path: Path
    encoding: str
    delimiter: str
    headers: list[str]
    rows: list[list[str]]

    def index(self, column: str) -> int:
        """Return the position of a logical column, or raise a clear error."""
        accepted = COLUMNS.get(column, (column,))
        wanted = {_header_key(name) for name in accepted}
        for position, header in enumerate(self.headers):
            if _header_key(header) in wanted:
                return position
        raise SourceFormatError(
            f"{self.path.name} : colonne attendue absente : {column!r} "
            f"(en-têtes trouvés : {', '.join(self.headers)})."
        )

    def has(self, column: str) -> bool:
        try:
            self.index(column)
        except SourceFormatError:
            return False
        return True

    def column(self, column: str) -> list[str]:
        position = self.index(column)
        return [
            row[position].strip() if position < len(row) else "" for row in self.rows
        ]

    def records(self, *columns: str) -> list[dict[str, str]]:
        """Return the rows as dicts restricted to ``columns`` (all required)."""
        positions = {name: self.index(name) for name in columns}
        return [
            {
                name: row[pos].strip() if pos < len(row) else ""
                for name, pos in positions.items()
            }
            for row in self.rows
            if any(cell.strip() for cell in row)
        ]


def read_source(path: Path) -> SourceTable:
    """Read a source CSV file, detecting its encoding and delimiter."""
    if not path.is_file():
        raise SourceFormatError(f"{path} : fichier introuvable.")
    text, encoding = _decode(path.read_bytes())
    header_line = text.split("\n", 1)[0]
    delimiter = _detect_delimiter(header_line, path)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = [row for row in reader if row]
    if not rows:
        raise SourceFormatError(f"{path.name} : fichier vide.")
    return SourceTable(path, encoding, delimiter, rows[0], rows[1:])


# --- Tables -------------------------------------------------------------------


@dataclass
class Cog:
    """Current communes and the links needed to resolve former codes."""

    communes: dict[str, tuple[str, str, str]]  # insee -> (name, dep, reg)
    parent: dict[str, str]  # COMA/COMD/ARM code -> current commune
    # (TYPECOM, code, name, COMPARENT) of every COMA/COMD row
    former: list[tuple[str, str, str, str]]


def read_communes(path: Path) -> Cog:
    table = read_source(path)
    communes: dict[str, tuple[str, str, str]] = {}
    parent: dict[str, str] = {}
    former: list[tuple[str, str, str, str]] = []
    for row in table.records("TYPECOM", "COM", "DEP", "REG", "LIBELLE", "COMPARENT"):
        kind, code = row["TYPECOM"].upper(), row["COM"]
        if kind == "COM":
            communes[code] = (row["LIBELLE"], row["DEP"], row["REG"])
        elif kind in ("COMA", "COMD", "ARM") and row["COMPARENT"]:
            parent.setdefault(code, row["COMPARENT"])
            if kind != "ARM":
                former.append((kind, code, row["LIBELLE"], row["COMPARENT"]))
    return Cog(communes, parent, former)


class Resolver:
    """Follow merger chains from an old commune code to a current commune."""

    def __init__(self, cog: Cog, movements: list[dict[str, str]]) -> None:
        self.cog = cog
        self.edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for row in movements:
            if (
                row["TYPECOM_AV"].upper() == "COM"
                and row["TYPECOM_AP"].upper() == "COM"
                and row["COM_AV"] != row["COM_AP"]
            ):
                self.edges[row["COM_AV"]].append((row["DATE_EFF"], row["COM_AP"]))

    def resolve(self, code: str) -> str | None:
        seen: set[str] = set()
        while code not in seen:
            if code in self.cog.communes:
                return code
            seen.add(code)
            if code in self.cog.parent:
                code = self.cog.parent[code]
                continue
            targets = self.edges.get(code)
            if not targets:
                return None
            code = max(targets)[1]  # latest movement
        return None


def build_history(
    cog: Cog,
    movements: list[dict[str, str]],
    since_1943: list[dict[str, str]],
) -> list[tuple[str, str, str, str, str]]:
    """Return ``(former name, former INSEE, current INSEE, nature, date)`` rows.

    ``nature`` is ``associee`` / ``deleguee`` when the pair (former code, name)
    is a COMA / COMD row of the current COG, else ``renommage`` for a renaming
    (movement ``MOD = 10``, or a past name under the commune's own code), else
    ``fusion``. The date is that of the latest movement for the pair.
    """
    resolver = Resolver(cog, movements)
    status = {
        (code, normalize(name)): "associee" if kind == "COMA" else "deleguee"
        for kind, code, name, _ in cog.former
    }
    # (normalized name, current code) -> (name, former code, nature, date)
    entries: dict[tuple[str, str], tuple[str, str, str, str]] = {}

    def add(
        name: str, old_code: str, insee: str | None, date: str, renaming: bool
    ) -> None:
        if not name or insee is None or insee not in cog.communes:
            return
        key = normalize(name)
        if key == normalize(cog.communes[insee][0]):
            return
        nature = status.get((old_code, key)) or ("renommage" if renaming else "fusion")
        previous = entries.get((key, insee))
        if previous is None or date > previous[3]:
            entries[(key, insee)] = (
                previous[0] if previous else name,
                old_code,
                nature,
                date,
            )

    for _, code, name, comparent in cog.former:
        add(name, code, resolver.resolve(comparent), "", False)
    for row in movements:
        if row["TYPECOM_AV"].upper() != "COM":
            continue
        old_code, new_code = row["COM_AV"], row["COM_AP"]
        target = resolver.resolve(new_code)
        # A commune still current under its old code (re-established, or source
        # of a split) keeps its own name: it is not a former name of another.
        if old_code in cog.communes and old_code != target:
            continue
        add(row["LIBELLE_AV"], old_code, target, row["DATE_EFF"], row["MOD"] == "10")
    for row in since_1943:
        if row["TYPECOM"].upper() != "COM" or not row["DATE_FIN"]:
            continue
        target = resolver.resolve(row["COM"])
        add(row["LIBELLE"], row["COM"], target, row["DATE_FIN"], target == row["COM"])

    return [
        (name, old_code, insee, nature, date)
        for (_, insee), (name, old_code, nature, date) in sorted(
            entries.items(), key=lambda item: (item[1][0], item[0][1])
        )
    ]


def read_departments(path: Path) -> list[tuple[str, str, str]]:
    table = read_source(path)
    return sorted(
        (row["DEP"], row["LIBELLE"], row["REG"])
        for row in table.records("DEP", "LIBELLE", "REG")
    )


def _region_names(path: Path) -> list[tuple[str, str]]:
    table = read_source(path)
    name_column = next(
        (c for c in REGION_NAME_COLUMNS if table.has(c)), REGION_NAME_COLUMNS[0]
    )
    return [(row["REG"], row[name_column]) for row in table.records("REG", name_column)]


def read_regions(current: Path, before_2016: Path) -> list[tuple[str, str, str]]:
    rows = [(code, name, "0") for code, name in sorted(_region_names(current))]
    current_keys = {normalize(name) for _, name, _ in rows}
    for code, name in sorted(_region_names(before_2016)):
        if normalize(name) not in current_keys:
            rows.append((code, name, "1"))
    return rows


def read_countries(path: Path) -> list[tuple[str, str]]:
    table = read_source(path)
    countries = {
        (row["LIBCOG"], row["LIBENR"])
        for row in table.records("LIBCOG", "LIBENR")
        if row["LIBCOG"]
    }
    return sorted(countries)


def read_postal_codes(path: Path, resolver: Resolver) -> list[tuple[str, str]]:
    table = read_source(path)
    pairs: set[tuple[str, str]] = set()
    unknown: set[str] = set()
    for row in table.records("CODE_COMMUNE_INSEE", "CODE_POSTAL"):
        insee = resolver.resolve(row["CODE_COMMUNE_INSEE"])
        if insee is None:
            unknown.add(row["CODE_COMMUNE_INSEE"])
            continue
        pairs.add((row["CODE_POSTAL"], insee))
    if unknown:
        print(
            f"{path.name} : {len(unknown)} code(s) INSEE inconnu(s) du COG ignoré(s) "
            f"({', '.join(sorted(unknown)[:10])}).",
            file=sys.stderr,
        )
    return sorted(pairs)


# --- Output -------------------------------------------------------------------


def _write_table(
    directory: Path, name: str, header: Sequence[str], rows: Sequence[Sequence[str]]
) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    data = gzip.compress(buffer.getvalue().encode("utf-8"), compresslevel=9, mtime=0)
    (directory / name).write_bytes(data)


def build(args: argparse.Namespace) -> None:
    cog = read_communes(args.communes)
    movements = read_source(args.mouvements).records(
        "MOD", "DATE_EFF", "TYPECOM_AV", "COM_AV", "LIBELLE_AV", "TYPECOM_AP", "COM_AP"
    )
    since_1943 = (
        read_source(args.communes_depuis_1943).records(
            "TYPECOM", "COM", "LIBELLE", "DATE_FIN"
        )
        if args.communes_depuis_1943
        else []
    )
    resolver = Resolver(cog, movements)
    tables: dict[str, tuple[tuple[str, ...], Sequence[Sequence[str]]]] = {
        "communes.csv.gz": (
            ("insee", "nom", "departement", "region"),
            [(code, *values) for code, values in sorted(cog.communes.items())],
        ),
        "historique.csv.gz": (
            ("ancien_nom", "ancien_insee", "insee_actuel", "nature", "date_effet"),
            build_history(cog, movements, since_1943),
        ),
        "departements.csv.gz": (
            ("code", "nom", "region"),
            read_departments(args.departements),
        ),
        "regions.csv.gz": (
            ("code", "nom", "avant_2016"),
            read_regions(args.regions, args.regions_2015),
        ),
        "pays.csv.gz": (("nom", "nom_officiel"), read_countries(args.pays)),
        "codes_postaux.csv.gz": (
            ("code_postal", "insee"),
            read_postal_codes(args.codes_postaux, resolver),
        ),
    }
    # Everything is read and checked before anything is written.
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    for name, (header, rows) in tables.items():
        _write_table(output, name, header, rows)
    (output / "VERSION").write_text(
        f"cog={args.cog_vintage}\npostal={args.postal_vintage}\n", encoding="utf-8"
    )
    sizes = sum((output / name).stat().st_size for name in tables)
    print(
        f"{len(cog.communes)} communes, {len(tables['historique.csv.gz'][1])} "
        f"anciens noms, {len(tables['codes_postaux.csv.gz'][1])} codes postaux ; "
        f"{sizes / 1_000_000:.2f} Mo écrits dans {output}."
    )


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Construit les données de référence embarquées (COG INSEE, codes "
            "postaux La Poste) à partir des fichiers déjà téléchargés."
        )
    )
    required = {
        "--communes": "v_commune_<millésime>.csv (COG)",
        "--mouvements": "v_mvt_commune_<millésime>.csv (COG)",
        "--departements": "v_departement_<millésime>.csv (COG)",
        "--regions": "v_region_<millésime>.csv (COG)",
        "--regions-2015": "fichier des régions du COG 2015 (régions d'avant 2016)",
        "--pays": "v_pays_territoire_<millésime>.csv (COG)",
        "--codes-postaux": "base officielle des codes postaux (La Poste)",
    }
    for option, help_text in required.items():
        parser.add_argument(option, type=Path, required=True, help=help_text)
    parser.add_argument(
        "--communes-depuis-1943",
        type=Path,
        help="v_commune_depuis_1943.csv (COG), facultatif : anciens noms",
    )
    parser.add_argument("--cog-vintage", required=True, help="millésime du COG")
    parser.add_argument(
        "--postal-vintage",
        required=True,
        help="millésime des codes postaux (date de téléchargement)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"dossier de sortie (défaut : {DEFAULT_OUTPUT})",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        build(args)
    except SourceFormatError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
