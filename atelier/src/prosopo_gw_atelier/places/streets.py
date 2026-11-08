"""Read the street of an occurrence complement and reduce it to a key.

``street_key`` is deterministic and shared by the offline Paris street table
builder and the application: both sides must compute the same key.
"""

from __future__ import annotations

import re

from ..refdata import normalize

# A street starts at its type word (full or abbreviated); "r." and "pl." only
# count with their dot so that stray letters do not match.
_TYPE_WORD = re.compile(
    r"(?<!\w)(?:rue|boulevard|bd|boul|bould|avenue|av|place|quai|impasse|imp"
    r"|passage|pass|faubourg|faub|fbg|fg)(?!\w)\.?"
    r"|(?<!\w)(?:r|pl|q)\.",
    re.IGNORECASE,
)
_SEGMENT_END = re.compile(r"[,;()\[\]]")
# "n° 5", "nº5", "no 5", "no. 5" and everything after.
_NUMBER_MARK = re.compile(
    r"\s*(?<!\w)n\s*[°º]\s*\d.*$|\s*(?<!\w)no\.?\s+\d.*$", re.IGNORECASE
)
_TRAILING_NUMBER = re.compile(r"\s+\d+\s*(?:bis|ter|quater)?\.?\s*$", re.IGNORECASE)

_EXPANSION = {
    "r": "rue",
    "bd": "boulevard",
    "boul": "boulevard",
    "bould": "boulevard",
    "av": "avenue",
    "pl": "place",
    "fg": "faubourg",
    "fbg": "faubourg",
    "faub": "faubourg",
    "q": "quai",
    "imp": "impasse",
    "pass": "passage",
    "ste": "sainte",
    "st": "saint",
}
_ARTICLES = frozenset({"de", "du", "des", "la", "le", "les", "l", "d"})
_SUFFIXES = frozenset({"bis", "ter", "quater"})


def street_of(complement: str | None) -> str | None:
    """Return the street text of a place complement, or None.

    The street runs from its type word to the next comma or parenthesis; house
    number and ``n°`` mark are not part of it.
    """
    if not complement:
        return None
    match = _TYPE_WORD.search(complement)
    if match is None:
        return None
    rest = complement[match.start() :]
    end = _SEGMENT_END.search(rest)
    if end is not None:
        rest = rest[: end.start()]
    rest = _NUMBER_MARK.sub("", rest)
    rest = _TRAILING_NUMBER.sub("", rest).strip()
    # Nothing left after the type word: not a street.
    if len(normalize(rest).split()) < 2:
        return None
    return rest


def street_key(street: str) -> str:
    """Return the comparison key of a street.

    Lowercase, no accents (``refdata.normalize``), type and saint
    abbreviations expanded, hyphens and apostrophes as spaces, articles
    (``de``, ``du``, ``des``, ``de la``, ``l'``, ``d'``, ``la``, ``le``,
    ``les``) dropped except in first position, ``n° N`` marks and house
    numbers (leading, with ``bis``/``ter``, or trailing) dropped; a number
    inside the name (``rue du 4 septembre``) is kept.
    """
    text = _SEGMENT_END.sub(" ", _NUMBER_MARK.sub("", street))
    tokens = [_EXPANSION.get(word, word) for word in normalize(text).split()]
    while tokens and tokens[0].isdigit():
        tokens.pop(0)
        if tokens and tokens[0] in _SUFFIXES:
            tokens.pop(0)
    while tokens and (tokens[-1].isdigit() or tokens[-1] in _SUFFIXES):
        tokens.pop()
    kept = [t for i, t in enumerate(tokens) if i == 0 or t not in _ARTICLES]
    return " ".join(kept)
