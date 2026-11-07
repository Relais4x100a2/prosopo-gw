"""Write the ``refdata_mini`` fixture in the generated reference data format.

Hand-picked extract of the INSEE COG 2026 and La Poste postal code base: Nord
(59), Pas-de-Calais (62), Rhône (69), plus the homonym pair "Merville" (59400 in
Nord, 31341 in Haute-Garonne). Lomme (59355) merged into Lille (59350) on
2000-02-27 is the merged-commune case. Public administrative data only.

Run from the repository root to regenerate the committed ``*.csv.gz`` files::

    uv run --package prosopo-gw-atelier python \\
        atelier/tests/fixtures/make_refdata_mini.py
"""

from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent / "refdata_mini"

TABLES: dict[str, list[list[str]]] = {
    "communes.csv.gz": [
        ["insee", "nom", "departement", "region"],
        ["31341", "Merville", "31", "76"],
        ["59183", "Dunkerque", "59", "32"],
        ["59350", "Lille", "59", "32"],
        ["59400", "Merville", "59", "32"],
        ["59512", "Roubaix", "59", "32"],
        ["62041", "Arras", "62", "32"],
        ["62765", "Saint-Omer", "62", "32"],
        ["69123", "Lyon", "69", "84"],
        ["69266", "Villeurbanne", "69", "84"],
    ],
    "historique.csv.gz": [
        ["ancien_nom", "insee_actuel", "date_effet"],
        ["Fort-Mardyck", "59183", ""],
        ["Hellemmes-Lille", "59350", ""],
        ["Lomme", "59350", "2000-02-27"],
    ],
    "departements.csv.gz": [
        ["code", "nom", "region"],
        ["31", "Haute-Garonne", "76"],
        ["59", "Nord", "32"],
        ["62", "Pas-de-Calais", "32"],
        ["69", "Rhône", "84"],
    ],
    "regions.csv.gz": [
        ["code", "nom", "avant_2016"],
        ["32", "Hauts-de-France", "0"],
        ["76", "Occitanie", "0"],
        ["84", "Auvergne-Rhône-Alpes", "0"],
        ["22", "Picardie", "1"],
        ["31", "Nord-Pas-de-Calais", "1"],
        ["73", "Midi-Pyrénées", "1"],
        ["82", "Rhône-Alpes", "1"],
    ],
    "pays.csv.gz": [
        ["nom", "nom_officiel"],
        ["Belgique", "Royaume de Belgique"],
        ["France", "République française"],
    ],
    "codes_postaux.csv.gz": [
        ["code_postal", "insee"],
        ["31330", "31341"],
        ["59000", "59350"],
        ["59100", "59512"],
        ["59140", "59183"],
        ["59160", "59350"],
        ["59260", "59350"],
        ["59660", "59400"],
        ["59777", "59350"],
        ["59800", "59350"],
        ["62000", "62041"],
        ["62500", "62765"],
        *[[f"6900{i}", "69123"] for i in range(1, 10)],
        ["69100", "69266"],
    ],
}

VERSION = "cog=2026\npostal=2026-11-07\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, rows in TABLES.items():
        buffer = io.StringIO()
        csv.writer(buffer, delimiter=";", lineterminator="\n").writerows(rows)
        data = gzip.compress(buffer.getvalue().encode("utf-8"), mtime=0)
        (OUTPUT / name).write_bytes(data)
    (OUTPUT / "VERSION").write_text(VERSION, encoding="utf-8")


if __name__ == "__main__":
    main()
