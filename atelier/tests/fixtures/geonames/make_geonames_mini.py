"""Generate the tiny synthetic GeoNames fixtures (run: python make_geonames_mini.py).

Real place names, invented geonameids and populations. Produces ``CA.zip``,
``GB.zip`` (a ``<CC>.txt`` plus a ``readme.txt``), ``admin1CodesASCII.txt``,
``admin2Codes.txt`` and ``countryInfo.txt``, next to this script.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def row(
    gid: int,
    name: str,
    alternates: str,
    fclass: str,
    fcode: str,
    country: str,
    admin1: str,
    admin2: str,
    population: int,
    lat: float = 50.0,
    lon: float = -97.0,
) -> str:
    fields = [
        str(gid), name, name, alternates, str(lat), str(lon), fclass, fcode, country,
        "", admin1, admin2, "", "", str(population), "", "10", "UTC", "2024-01-01",
    ]  # fmt: skip
    return "\t".join(fields)


CA = [
    row(
        9000001,
        "Winnipeg",
        "Ouinipègue,Winnipeg,R3C,http://en.wikipedia.org/wiki/Winnipeg,YW9,W,Winipeg",
        "P",
        "PPLA",
        "CA",
        "03",
        "",
        705000,
        49.88,
        -97.17,
    ),
    row(
        9000002,
        "Manitoba",
        "Manitoba,Manitoba Province",
        "A",
        "ADM1",
        "CA",
        "03",
        "",
        1200000,
        55.0,
        -98.0,
    ),
    row(9000003, "Ontario", "", "A", "ADM1", "CA", "08", "", 14000000, 50.0, -85.0),
    row(9000004, "Beaumont", "", "P", "PPL", "CA", "03", "", 1200, 50.1, -97.5),
    row(9000005, "Beaumont", "", "P", "PPL", "CA", "08", "", 800, 45.2, -76.1),
    row(9000006, "Rosedale", "", "P", "PPL", "CA", "03", "", 300, 50.3, -97.8),
    row(9000007, "Rosedale", "", "P", "PPL", "CA", "03", "", 150, 49.6, -98.4),
    row(9000008, "Mount Fictive", "", "T", "MT", "CA", "03", "", 0),
    row(9000009, "Fictive Creek", "", "H", "STM", "CA", "08", "", 0),
]
GB = [
    row(
        9100001,
        "Storrington",
        "Storrington and Sullington,RH20,ZZZ,Storringtown",
        "P",
        "PPL",
        "GB",
        "ENG",
        "P5",
        7800,
        50.92,
        -0.45,
    ),
    row(
        9100002,
        "England",
        "Angleterre",
        "A",
        "ADM1",
        "GB",
        "ENG",
        "",
        55000000,
        52.0,
        -1.0,
    ),
    row(9100003, "East Sussex", "", "A", "ADM2", "GB", "ENG", "P5", 840000, 50.9, 0.3),
    row(9100004, "Fictive Hill", "", "T", "HLL", "GB", "ENG", "P5", 0),
]
ADMIN1 = [
    "CA.03\tManitoba\tManitoba\t9000002",
    "CA.08\tOntario\tOntario\t9000003",
    "GB.ENG\tEngland\tEngland\t9100002",
    "FR.A1\tNowhere\tNowhere\t9200001",
]
ADMIN2 = [
    "GB.ENG.P5\tEast Sussex\tEast Sussex\t9100003",
    "FR.A1.01\tNowhere\tNowhere\t9200002",
]
COUNTRY_INFO = [
    "#ISO\tISO3\tISO-Numeric\tfips\tCountry\tCapital\tArea(in sq km)",
    "CA\tCAN\t124\tCA\tCanada\tOttawa\t9984670",
    "GB\tGBR\t826\tUK\tUnited Kingdom\tLondon\t244820",
]


def write_zip(path: Path, country: str, lines: list[str]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{country}.txt", "\n".join(lines) + "\n")
        archive.writestr("readme.txt", "synthetic fixture\n")


def main() -> None:
    write_zip(HERE / "CA.zip", "CA", CA)
    write_zip(HERE / "GB.zip", "GB", GB)
    (HERE / "admin1CodesASCII.txt").write_text(
        "\n".join(ADMIN1) + "\n", encoding="utf-8"
    )
    (HERE / "admin2Codes.txt").write_text("\n".join(ADMIN2) + "\n", encoding="utf-8")
    (HERE / "countryInfo.txt").write_text(
        "\n".join(COUNTRY_INFO) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
