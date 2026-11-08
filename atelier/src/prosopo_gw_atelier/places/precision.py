"""Precision of an occurrence: which arrondissement (and quartier) it designates.

Three clues, in the author's order: the code (an INSEE or postal code, which names
the arrondissement in force today), the written number (read against the date of
the occurrence) and the street (Paris only, through the street table, against the
date). Two clues naming two arrondissements make a ``conflict``; nothing is decided
silently. A street lying in several arrondissements is ``ambiguous``, never guessed.
An occurrence without a year keeps the written number without a period and its
street is not read.

An occurrence is ``uncertain`` when its year is the Paris transition year (1860),
when an approximate date (``~ ? < > .. |``), or the range it spells, reaches
1859-1861, when it precedes the creation of the arrondissement in Lyon or
Marseille, or when a code (which names a current arrondissement) sits on an
occurrence before 1860.

Before 1860 a code is not compared with the street: the street gives the
arrondissement of the date, the code only the current one; the result is
``uncertain`` and carries the street candidates.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ..refdata.arrondissements import CITY_INSEE, City, current, former_paris
from ..refdata.paris_table import ParisTable, StreetHit
from .levels import Level
from .model import Occurrence, WrittenArrondissement
from .streets import street_key, street_of

PrecisionStatus = Literal["applied", "conflict", "uncertain", "ambiguous"]
Clue = Literal["code", "number", "street", "manual"]

PERIOD_PARIS_OLD = "paris-1795"
PERIOD_PARIS_NEW = "paris-1860"
_TRANSITION_YEAR = 1860
_APPROXIMATE_MARKS = ("~", "?", "<", ">", "..", "|")
_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)")


@dataclass(frozen=True)
class Candidate:
    """One arrondissement proposed by a clue (``arrondissement_id`` empty = none)."""

    arrondissement_id: str
    quartier_id: str | None
    quartier: str | None
    clue: Clue


@dataclass(frozen=True)
class Precision:
    """Outcome for one occurrence; ``applied`` holds exactly one candidate."""

    period: str
    status: PrecisionStatus
    candidates: tuple[Candidate, ...]


def period_of(city: City, year: int | None) -> str:
    """Period of an occurrence: Paris splits at 1860, ``""`` when undated."""
    if year is None:
        return ""
    if city == "paris":
        return PERIOD_PARIS_OLD if year < _TRANSITION_YEAR else PERIOD_PARIS_NEW
    return city


def _city_of_levels(levels: Sequence[Level]) -> City | None:
    codes = {code: city for city, code in CITY_INSEE.items()}
    for level in levels:
        if level.type == "commune" and level.identifier in codes:
            return codes[level.identifier or ""]
    return None


def _is_approximate(date: str | None) -> bool:
    return date is not None and any(mark in date for mark in _APPROXIMATE_MARKS)


def _approximate_near_transition(occurrence: Occurrence) -> bool:
    """Tell whether an approximate date, or its range, reaches 1859-1861."""
    if not _is_approximate(occurrence.date) or occurrence.year is None:
        return False
    years = [occurrence.year, *(int(y) for y in _YEAR.findall(occurrence.date or ""))]
    return min(years) <= 1861 and max(years) >= 1859


def _is_uncertain_date(city: City, number: int | None, occurrence: Occurrence) -> bool:
    year = occurrence.year
    if year is None:
        return False
    if city == "paris":
        if year == _TRANSITION_YEAR:
            return True
        return _approximate_near_transition(occurrence)
    if number is not None:
        created = current(city, number)
        if created is not None and year < int(created.start[:4]):
            return True
    return False


def _written_candidate(
    city: City, written: WrittenArrondissement, year: int | None
) -> tuple[Candidate, bool]:
    """Candidate of the code or number, and whether it can be compared by id.

    A code names the arrondissement in force today; before 1860 in Paris it is
    not comparable with the street of the date.
    """
    number = written.number
    if written.clue == "code":
        found = current(city, number)
        ident = found.id if found is not None else ""
        comparable = not (city == "paris" and year is not None and year < 1860)
        return Candidate(ident, None, None, "code"), comparable
    if city != "paris":
        found = current(city, number)
        return Candidate(found.id if found else "", None, None, "number"), True
    if year is None:
        return Candidate(f"paris-{number:02d}", None, None, "number"), True
    if year < _TRANSITION_YEAR:
        old = former_paris(number)
        return Candidate(old.id if old else "", None, None, "number"), True
    found = current("paris", number)
    return Candidate(found.id if found else "", None, None, "number"), True


def _street_groups(
    hits: tuple[StreetHit, ...],
) -> dict[str, tuple[StreetHit, ...]]:
    groups: dict[str, list[StreetHit]] = {}
    for hit in hits:
        groups.setdefault(hit.arrondissement_id, []).append(hit)
    return {k: tuple(v) for k, v in groups.items()}


def _quartier_of(hits: tuple[StreetHit, ...]) -> tuple[str | None, str | None]:
    """Quartier shared by every hit of one arrondissement, else none."""
    found = {(h.quartier_id, h.quartier) for h in hits}
    if len(found) == 1:
        return next(iter(found))
    return None, None


def _street_candidate(arrondissement_id: str, hits: tuple[StreetHit, ...]) -> Candidate:
    quartier_id, quartier = _quartier_of(hits)
    return Candidate(arrondissement_id, quartier_id, quartier, "street")


def _street_hits(
    city: City, occurrence: Occurrence, period: str, table: ParisTable
) -> tuple[StreetHit, ...]:
    if city != "paris" or occurrence.year is None:
        return ()
    street = street_of(occurrence.complement)
    if street is None:
        return ()
    return table.streets(street_key(street), period)


def precise(
    levels: Sequence[Level],
    arrondissement: WrittenArrondissement | None,
    occurrence: Occurrence,
    table: ParisTable,
) -> Precision | None:
    """Return the precision of an occurrence, or ``None`` when no clue applies.

    ``None`` outside Paris, Lyon and Marseille (no ``commune`` level with their
    INSEE code), and when there is neither a written arrondissement nor a street
    that the table knows for the date.
    """
    city = _city_of_levels(levels)
    if city is None:
        return None
    written = (
        arrondissement
        if arrondissement is not None and arrondissement.city == city
        else None
    )
    period = period_of(city, occurrence.year)
    uncertain = _is_uncertain_date(
        city, written.number if written else None, occurrence
    )
    primary: Candidate | None = None
    comparable = True
    if written is not None:
        primary, comparable = _written_candidate(city, written, occurrence.year)
        if not comparable:
            uncertain = True
    groups = _street_groups(_street_hits(city, occurrence, period, table))
    plain: PrecisionStatus = "uncertain" if uncertain else "applied"

    if not groups:
        if primary is None:
            return None
        status: PrecisionStatus = "conflict" if not primary.arrondissement_id else plain
        return Precision(period, status, (primary,))

    street = tuple(_street_candidate(k, v) for k, v in groups.items())
    if primary is None or not comparable:
        if len(street) > 1:
            return Precision(period, "ambiguous", street)
        return Precision(period, "uncertain" if primary else plain, street)
    if primary.arrondissement_id in groups:
        quartier_id, quartier = _quartier_of(groups[primary.arrondissement_id])
        merged = Candidate(
            primary.arrondissement_id, quartier_id, quartier, primary.clue
        )
        return Precision(period, plain, (merged,))
    return Precision(period, "conflict", (primary, *street))
