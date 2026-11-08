"""Arrondissements of Paris, Lyon and Marseille: codes, names and periods.

Codes follow fixed rules, so no data file is needed. Paris: INSEE ``751NN``,
postal ``750NN`` (and ``75116`` for the 16th). Lyon: INSEE ``6938N``, postal
``6900N``. Marseille: INSEE ``132NN``, postal ``130NN``.

Creation dates, checked against public sources (2026-11-08):

* Paris: law of 11 October 1795 (19 vendemiaire an IV) created twelve
  arrondissements; the law of 16 June 1859 replaced them by twenty from
  1 January 1860 (Archives nationales place records; Wikipedia, "Arrondissements
  of Paris (1795-1859)" as a pointer to the law). The old ones end 1859-12-31.
* Lyon: Archives municipales de Lyon, "Dates de creation des arrondissements"
  (archives-lyon.fr, dates_creation_arrondissements.pdf): 1st-5th by decree of
  24 March 1852; 6th by law of 17 July 1867; 7th by law of 8 March 1912; 8th by
  presidential ordinance of 9 February 1959; 9th by decree of 12 August 1964.
  (The task brief gave 1867-03-08, 1912-07-08, 1959-07-12 and 1964-02-12; the
  municipal archives contradict them, so their dates are used.)
* Marseille: decree no. 46-2285 of 18 October 1946 divides the commune into
  sixteen arrondissements (Code general des collectivites territoriales,
  art. D2513-1). The brief's 1946-03-12 is not supported by that text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

City = Literal["paris", "lyon", "marseille"]

CITY_INSEE: dict[City, str] = {"paris": "75056", "lyon": "69123", "marseille": "13055"}

_COUNT: dict[City, int] = {"paris": 20, "lyon": 9, "marseille": 16}

_PARIS_OLD_START = "1795-10-11"
_PARIS_OLD_END = "1859-12-31"
_PARIS_START = "1860-01-01"
_LYON_START = {
    **dict.fromkeys(range(1, 6), "1852-03-24"),
    6: "1867-07-17",
    7: "1912-03-08",
    8: "1959-02-09",
    9: "1964-08-12",
}
_MARSEILLE_START = "1946-10-18"


@dataclass(frozen=True)
class Arrondissement:
    """One arrondissement over a period (``end`` None = still in force)."""

    id: str
    city: City
    number: int
    name: str
    start: str
    end: str | None


def numbers(city: City) -> range:
    """Valid arrondissement numbers of a city."""
    return range(1, _COUNT[city] + 1)


def city_of(insee: str) -> City | None:
    """City whose commune code is ``insee``, if it has arrondissements."""
    for city, code in CITY_INSEE.items():
        if code == insee:
            return city
    return None


def level_name(number: int) -> str:
    """French name: ``1er arrondissement``, ``7e arrondissement``."""
    return f"{number}{'er' if number == 1 else 'e'} arrondissement"


def name_of(identifier: str) -> str | None:
    """Name of the arrondissement an identifier designates, or None.

    Reads ``paris-07``, ``paris-1795-07`` and the INSEE or postal codes
    (``75107``, ``69381``, ``13216``).
    """
    if identifier.startswith("paris-"):
        number = identifier.rsplit("-", 1)[-1]
        if number.isdigit() and int(number) in numbers("paris"):
            return level_name(int(number))
        return None
    found = by_code(identifier)
    return level_name(found[1]) if found is not None else None


def _insee_code(city: City, number: int) -> str:
    if city == "paris":
        return f"751{number:02d}"
    if city == "lyon":
        return f"6938{number}"
    return f"132{number:02d}"


def level_id(city: City, number: int) -> str:
    """Level identifier: ``paris-07`` for Paris, the INSEE code otherwise."""
    if city == "paris":
        return f"paris-{number:02d}"
    return _insee_code(city, number)


def current(city: City, number: int) -> Arrondissement | None:
    """Arrondissement in force today, or None if the number is out of range."""
    if number not in numbers(city):
        return None
    if city == "paris":
        start = _PARIS_START
    elif city == "lyon":
        start = _LYON_START[number]
    else:
        start = _MARSEILLE_START
    return Arrondissement(
        _insee_code(city, number), city, number, level_name(number), start, None
    )


def former_paris(number: int) -> Arrondissement | None:
    """Paris arrondissement of 1795-1859 (1 to 12)."""
    if not 1 <= number <= 12:
        return None
    return Arrondissement(
        f"paris-1795-{number:02d}",
        "paris",
        number,
        level_name(number),
        _PARIS_OLD_START,
        _PARIS_OLD_END,
    )


def by_code(code: str) -> tuple[City, int] | None:
    """Read an INSEE arrondissement code or a postal code of the three cities."""
    if len(code) != 5 or not code.isdigit():
        return None
    if code == "75116":
        return ("paris", 16)
    for city in CITY_INSEE:
        for number in numbers(city):
            if code == _insee_code(city, number) or code == _postal(city, number):
                return (city, number)
    return None


def is_insee_code(code: str) -> bool:
    """Tell whether ``code`` is the INSEE code of an arrondissement."""
    found = by_code(code)
    return found is not None and code == _insee_code(*found)


def _postal(city: City, number: int) -> str:
    prefix = {"paris": "750", "lyon": "690", "marseille": "130"}[city]
    return f"{prefix}{number:02d}"
