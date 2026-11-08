"""Decomposition of a place writing into typed elements (design § 6.1).

The writing is cut on ``,``, ``;``, ``(``, ``)``, `` - `` and around a
5-character code (5 digits, or ``2A``/``2B`` + 3 digits); the order of the
segments is free. Each segment is then read as:

- a 5-character code: INSEE code if the COG knows it, postal code if La Poste
  knows it; when it is both, the reading that agrees with the written commune
  wins (without a written commune, the INSEE reading wins if the postal code
  serves that commune, otherwise no element is kept and both readings become
  candidates); when it is neither, the writing is ``ambiguous`` and the code
  yields no element;
- the first text segment that names a commune (current or former name) is the
  commune; other segments are tried as department, region (current or pre-2016)
  and country first, then as a further commune name;
- anything else (``en mer``, a street…) yields no element.

Candidates are the INSEE codes allowed by the names, then narrowed by the codes
and the department. A constraint that would leave no candidate is ignored
(conflicting clues do not erase the commune). ``insee`` is set only when one
candidate remains and a commune name or an INSEE code supports it: a postal
code or a department alone proposes candidates without choosing. A name that
matches one current commune and former communes of others, with no other clue
deciding, is read as the current commune (the former one becomes the
``alternative``). Homonyms are expressed by ``insee is None`` and several
candidates; ``ambiguous`` stays ``False`` for them. Regions do not narrow the
candidates (the reference data only gives their name).

Every non-empty segment is kept, with its element or ``None``, so that
unrecognised levels (a foreign county, a state…) survive. The first segment
read as a commune name also yields the former-commune readings (renames left
out): ``historical`` when the resolved commune was matched only through a former
commune of that name, ``alternative`` when the current commune of that name is
resolved, or still among the candidates, while a former commune of the same
name belongs to another candidate (the first by former code).

The function is pure, deterministic and never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..refdata import Former, NameMatch, RefData
from ..refdata.arrondissements import (
    CITY_INSEE,
    City,
    by_code,
    city_of,
    is_insee_code,
    numbers,
)
from .model import Decomposition, Element, Segment, WrittenArrondissement

_CODE = r"(?:\d{5}|2[ABab]\d{3})"
_SPLIT = re.compile(rf"[,;()]|\s-\s|(?<!\w)({_CODE})(?!\w)")
_CODE_ONLY = re.compile(rf"^{_CODE}$")
_STRIP = " \t\r\n-–—.:'\"’"

HINT_NAME = "nom"
HINT_POSTAL = "code postal"
HINT_INSEE = "code INSEE"
HINT_DEPARTMENT = "département"
HINT_OLD_REGION = "ancienne région"
HINT_REGION = "région"
HINT_COUNTRY = "pays"
HINT_FORMER_NAME = "ancien nom"
HINT_ARR_NUMBER = "numéro d'arrondissement"
HINT_ARR_CODE = "code d'arrondissement"

_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
}  # fmt: skip
_ORDINAL = r"(?i:ère|ere|er|re|ème|eme|è|e)"
_WORD = r"(?i:arrondissement|arr\.?)"
_NUM = rf"(?:\d{{1,2}}{_ORDINAL}|[IVX]{{1,5}}(?:{_ORDINAL})?)"
_TOKEN = rf"(?:{_NUM}(?:\s+{_WORD})?|{_WORD}\s+(?:\d{{1,2}}|[IVX]{{1,5}}))(?!\w)"
_DE = r"(?i:de|du|d['’])\s*"
_ARR_ALONE = re.compile(rf"^(?P<token>{_TOKEN})$")
_ARR_FIRST = re.compile(rf"^(?P<token>{_TOKEN})\s+(?:{_DE})?(?P<rest>.+)$")
_ARR_LAST = re.compile(rf"^(?P<rest>.+?)\s+(?P<token>{_TOKEN})$")


def _arrondissement_token(segment: str) -> tuple[str, str, int] | None:
    """Return ``(rest, token, number)`` of a segment naming an arrondissement."""
    for pattern in (_ARR_ALONE, _ARR_FIRST, _ARR_LAST):
        found = pattern.match(segment)
        if found is None:
            continue
        token = found.group("token")
        digits = re.search(r"\d{1,2}", token)
        if digits is not None:
            number = int(digits.group())
        else:
            roman = re.search(r"[IVX]+", token)
            number = _ROMAN.get(roman.group() if roman else "", 0)
        if not 1 <= number <= 20:
            return None
        rest = found.groupdict().get("rest") or ""
        return rest.strip(_STRIP), token, number
    return None


def split_arrondissement(segment: str) -> tuple[str, int] | None:
    """Split a segment naming an arrondissement into its rest and its number.

    Reads ``7e``, ``7è``, ``7ème``, ``1er``, ``1re``, ``1ère``, ``VIIe``, ``VII``,
    ``7e arr.``, ``7e arrondissement`` and ``arrondissement 7``, alone or before
    or after a name (``Paris 7e``, ``7e arrondissement de Paris``). Return the
    cleaned rest (possibly empty) and the number, or ``None``.
    """
    found = _arrondissement_token(segment)
    return None if found is None else (found[0], found[2])


def is_code(segment: str) -> bool:
    """Tell whether a cleaned segment is a 5-character (INSEE or postal) code."""
    return _CODE_ONLY.match(segment) is not None


def segments(writing: str) -> list[str]:
    """Cut a writing into its non-empty, stripped segments, in order."""
    parts = _SPLIT.split(writing)
    cleaned = (part.strip(_STRIP) for part in parts if part is not None)
    return [part for part in cleaned if part]


@dataclass
class _State:
    elements: list[tuple[int, Element]] = field(default_factory=list)
    names: set[str] | None = None
    insee_codes: list[set[str]] = field(default_factory=list)
    postal_codes: list[set[str]] = field(default_factory=list)
    department: str | None = None
    ambiguous: bool = False
    name_matches: list[NameMatch] = field(default_factory=list)


def _name_element(
    segment: str, ref: RefData
) -> tuple[Element, set[str], list[NameMatch]] | None:
    matches = ref.communes_by_name(segment)
    if not matches:
        return None
    codes = {m.commune.insee for m in matches}
    current = sorted({m.commune.name for m in matches if m.former_name is None})
    if current:
        value = current[0] if len(current) == 1 else segment
        return Element("commune", value, HINT_NAME), codes, matches
    former = sorted({m.former_name or segment for m in matches})
    value = former[0] if len(former) == 1 else segment
    return Element("former_name", value, HINT_FORMER_NAME), codes, matches


def _admin_element(segment: str, ref: RefData) -> Element | None:
    department = ref.department(segment)
    if department is not None:
        return Element("department", department, HINT_DEPARTMENT)
    region = ref.region(segment)
    if region is not None:
        name, before_2016 = region
        return Element("region", name, HINT_OLD_REGION if before_2016 else HINT_REGION)
    country = ref.country(segment)
    if country is not None:
        return Element("country", country, HINT_COUNTRY)
    return None


def _add_names(state: _State, codes: set[str]) -> None:
    if state.names is None:
        state.names = set(codes)
    elif state.names & codes:
        state.names &= codes


def _read_text(index: int, segment: str, ref: RefData, state: _State) -> None:
    named = _name_element(segment, ref)
    if named is not None and state.names is None:
        state.elements.append((index, named[0]))
        _add_names(state, named[1])
        # Only the first name segment feeds the historical/alternative readings.
        state.name_matches = named[2]
        return
    admin = _admin_element(segment, ref)
    if admin is not None:
        state.elements.append((index, admin))
        if admin.kind == "department" and state.department is None:
            state.department = admin.value
        return
    if named is not None:
        state.elements.append((index, named[0]))
        _add_names(state, named[1])


def _narrow(candidates: set[str], constraint: set[str]) -> set[str]:
    narrowed = candidates & constraint
    return narrowed if narrowed else candidates


def _insee_city(code: str, ref: RefData) -> City | None:
    """City of an arrondissement INSEE code, if the reference knows the city."""
    found = by_code(code)
    if found is None or not is_insee_code(code):
        return None
    return found[0] if ref.commune_by_insee(CITY_INSEE[found[0]]) else None


def _read_codes(
    codes: list[tuple[int, str]], ref: RefData, state: _State
) -> list[tuple[int, str, set[str], set[str]]]:
    """Classify each code; return the unresolved INSEE-or-postal ones."""
    undecided: list[tuple[int, str, set[str], set[str]]] = []
    for index, code in codes:
        commune = ref.commune_by_insee(code)
        insee = {commune.insee} if commune is not None else set()
        postal = {c.insee for c in ref.communes_by_postal(code)}
        if insee and postal:
            undecided.append((index, code, insee, postal))
        elif insee:
            state.elements.append((index, Element("insee_code", code, HINT_INSEE)))
            state.insee_codes.append(insee)
        elif postal:
            state.elements.append((index, Element("postal_code", code, HINT_POSTAL)))
            state.postal_codes.append(postal)
        elif (city := _insee_city(code, ref)) is not None:
            # INSEE code of an arrondissement: read as the INSEE of its city.
            state.elements.append(
                (index, Element("insee_code", CITY_INSEE[city], HINT_ARR_CODE))
            )
            state.insee_codes.append({CITY_INSEE[city]})
        else:
            state.ambiguous = True
    return undecided


def _settle_code(
    index: int, code: str, insee: set[str], postal: set[str], state: _State
) -> set[str] | None:
    """Pick the reading of a code that is both INSEE and postal.

    Return the candidates to add when no reading can be chosen.
    """
    names = state.names
    if names is not None and insee & names:
        reading = "insee"
    elif names is not None and postal & names:
        reading = "postal"
    elif names is None and insee <= postal:
        reading = "insee"
    else:
        return insee | postal
    if reading == "insee":
        state.elements.append((index, Element("insee_code", code, HINT_INSEE)))
        state.insee_codes.append(insee)
    else:
        state.elements.append((index, Element("postal_code", code, HINT_POSTAL)))
        state.postal_codes.append(postal)
    return None


def decompose(writing: str, ref: RefData) -> Decomposition:
    """Split ``writing`` into typed elements and resolve its commune if possible.

    A segment naming an arrondissement number (``Paris 7e``) is first read with
    the number set apart; it is kept only when the rest resolves a commune that
    has that arrondissement, otherwise the writing is read as written.
    """
    written = segments(writing)
    parts = [_Part(text) for text in written]
    expanded: list[_Part] = []
    found = False
    for text in written:
        token = None if is_code(text) else _arrondissement_token(text)
        if token is None:
            expanded.append(_Part(text))
            continue
        found = True
        rest, token_text, number = token
        if rest:
            expanded.append(_Part(rest))
        expanded.append(_Part(token_text, number))
    if found:
        result = _build(writing, expanded, ref, need_number=True)
        if result is not None:
            return result
    result = _build(writing, parts, ref, need_number=False)
    assert result is not None
    return result


@dataclass(frozen=True)
class _Part:
    """A written segment; ``number`` is set on an arrondissement token."""

    text: str
    number: int | None = None


def _build(
    writing: str, parts: list[_Part], ref: RefData, *, need_number: bool
) -> Decomposition | None:
    """Decompose ``parts``; ``None`` if ``need_number`` and no number fits."""
    state = _State()
    codes: list[tuple[int, str]] = []
    tokens: list[tuple[int, int]] = []
    written = [part.text for part in parts]
    for index, part in enumerate(parts):
        if part.number is not None:
            tokens.append((index, part.number))
        elif is_code(part.text):
            codes.append((index, part.text.upper()))
        else:
            _read_text(index, part.text, ref, state)

    unsettled: set[str] = set()
    for index, code, insee, postal in _read_codes(codes, ref, state):
        extra = _settle_code(index, code, insee, postal, state)
        if extra is not None:
            unsettled |= extra

    supported = state.names is not None or bool(state.insee_codes)
    candidates: set[str] | None = set(state.names) if state.names is not None else None
    for constraint in (*state.insee_codes, *state.postal_codes):
        candidates = (
            constraint if candidates is None else _narrow(candidates, constraint)
        )
    if unsettled:
        candidates = unsettled if candidates is None else _narrow(candidates, unsettled)
    if candidates is not None and state.department is not None:
        in_department = {
            code
            for code in candidates
            if (commune := ref.commune_by_insee(code)) is not None
            and commune.department == state.department
        }
        candidates = _narrow(candidates, in_department)

    ordered = tuple(sorted(candidates)) if candidates else ()
    insee_code = ordered[0] if supported and len(ordered) == 1 else None
    if insee_code is None:
        current = _current_reading(state.name_matches, set(ordered))
        if current is not None:
            insee_code, ordered = current, (current,)
    arrondissement = _arrondissement(insee_code, codes, tokens, state)
    if need_number:
        city = city_of(insee_code) if insee_code is not None else None
        if city is None or not any(n in numbers(city) for _, n in tokens):
            return None
    if arrondissement is not None and arrondissement[1] is not None:
        number = str(arrondissement[0].number)
        element = Element("arrondissement", number, HINT_ARR_NUMBER)
        state.elements.append((arrondissement[1], element))
    elements = tuple(element for _, element in sorted(state.elements, key=_index))
    by_index = dict(state.elements)
    historical, alternative = _former_readings(
        state.name_matches, insee_code, set(ordered)
    )
    return Decomposition(
        writing=writing,
        elements=elements,
        insee=insee_code,
        candidates=ordered,
        ambiguous=state.ambiguous,
        segments=tuple(
            Segment(text, by_index.get(index)) for index, text in enumerate(written)
        ),
        historical=historical,
        alternative=alternative,
        arrondissement=arrondissement[0] if arrondissement else None,
    )


def _arrondissement(
    insee: str | None,
    codes: list[tuple[int, str]],
    tokens: list[tuple[int, int]],
    state: _State,
) -> tuple[WrittenArrondissement, int | None] | None:
    """Arrondissement the writing names, and the index of its number token.

    The code wins over a number; a number that disagrees with the code is not
    retained (its segment stays an untyped level). The index is ``None`` when the
    arrondissement is named by a code alone, or by a code the number contradicts.
    """
    city = city_of(insee) if insee is not None else None
    if city is None:
        return None
    read = dict(state.elements)
    number_at = next(((i, n) for i, n in tokens if n in numbers(city)), None)
    for index, code in codes:
        element = read.get(index)
        found = by_code(code)
        if (
            element is not None
            and (element.kind == "postal_code" or element.hint == HINT_ARR_CODE)
            and found is not None
            and found[0] == city
        ):
            agreed = number_at is not None and number_at[1] == found[1]
            return (
                WrittenArrondissement(city, found[1], "code"),
                number_at[0] if agreed and number_at else None,
            )
    if number_at is None:
        return None
    return WrittenArrondissement(city, number_at[1], "number"), number_at[0]


def _current_reading(matches: list[NameMatch], candidates: set[str]) -> str | None:
    """Return the current commune an undecided name is read as (plan choice 5).

    The name must match exactly one current commune, and every other remaining
    candidate must come only from a former commune (not a rename) of that name.
    """
    current = {m.commune.insee for m in matches if m.former is None}
    if len(current) != 1 or not current <= candidates:
        return None
    formers = {
        m.commune.insee
        for m in matches
        if m.former is not None and m.former.nature != "renommage"
    }
    return next(iter(current)) if candidates <= current | formers else None


def _former_readings(
    matches: list[NameMatch], insee: str | None, candidates: set[str]
) -> tuple[Former | None, Former | None]:
    """Return the ``(historical, alternative)`` readings of the name segment."""
    current = {m.commune.insee for m in matches if m.former is None}
    formers = sorted(
        (m.former for m in matches if m.former and m.former.nature != "renommage"),
        key=lambda f: f.insee,
    )
    if insee is not None and insee not in current:
        historical = next((f for f in formers if f.current == insee), None)
        return historical, None
    retained = {insee} if insee is not None else current & candidates
    if not retained:
        return None, None
    others = [
        f
        for f in formers
        if f.current not in retained and (insee is not None or f.current in candidates)
    ]
    return None, others[0] if others else None


def _index(item: tuple[int, Element]) -> int:
    return item[0]
