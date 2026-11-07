"""Normalization of place names into comparison keys."""

from __future__ import annotations

import re
import unicodedata

# Characters that do not decompose under NFKD but have an ASCII spelling.
_LIGATURES = str.maketrans({"œ": "oe", "æ": "ae", "ß": "ss", "ø": "o", "đ": "d"})
# Hyphens, apostrophes (straight and typographic), underscores and dots
# separate words.
_SEPARATORS = re.compile(r"[-‐‑‒–—'’ʼ`´_.\s]+")
_ABBREVIATIONS = {"st": "saint", "ste": "sainte"}


def normalize(text: str) -> str:
    """Return the comparison key of a place name.

    Lowercase, without accents, hyphens/apostrophes/underscores/runs of spaces
    turned into one space, ``st``/``ste`` expanded to ``saint``/``sainte`` as
    whole words, no leading or trailing space.
    """
    lowered = text.casefold().translate(_LIGATURES)
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = _SEPARATORS.sub(" ", stripped).split()
    return " ".join(_ABBREVIATIONS.get(word, word) for word in words)
