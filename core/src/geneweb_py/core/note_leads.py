"""Pistes d'organisation dans le texte libre d'une note.

Voir ``core/doc/exports_design.md`` § 6. Une piste est un passage de note qui
contient un mot d'établissement ou une forme juridique : c'est un indice à
vérifier, pas une organisation. Le vocabulaire est celui de
``event_to_organization`` ; seules les formes juridiques (``SA``, ``SNC``…)
sont sensibles à la casse, sans quoi « sa » ou « et » déclencheraient partout.
"""

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .event_to_organization import (
    COMPANY_NAME_TRIGGERS,
    ESTABLISHMENT_WORDS,
    LEGAL_FORMS,
    _fold,
)
from .organization import OrganizationType

EXCERPT_RADIUS = 150
EXCERPT_MAX = 600

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# Mots (lettres seules) et nombres ; l'apostrophe et le tiret séparent
_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+")
_LINKING_WORDS = frozenset({"de", "du", "des", "d", "la", "le", "les", "l", "et"})
_AFTER_EN_COMPAGNIE = frozenset({"de", "d", "des", "du"})
_ABBREVIATED_FORM = "Et."


@dataclass(frozen=True)
class NoteLead:
    """Passage d'une note qui évoque une organisation."""

    start: int
    end: int
    words: Tuple[str, ...]
    guessed_type: str
    strong: bool
    excerpt: str


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int

    @property
    def folded(self) -> str:
        return _fold(self.text)

    @property
    def capitalized(self) -> bool:
        return self.text[:1].isupper()


@dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    word: str
    type: str
    strong: bool


def _tokens(text: str) -> List[_Token]:
    tokens: List[_Token] = []
    for match in _TOKEN_RE.finditer(text):
        word, start, end = match.group(), match.start(), match.end()
        if word + text[end : end + 1] == _ABBREVIATED_FORM:
            word, end = _ABBREVIATED_FORM, end + 1
        tokens.append(_Token(word, start, end))
    return tokens


def _at(tokens: List[_Token], index: int) -> Optional[_Token]:
    return tokens[index] if 0 <= index < len(tokens) else None


def _is_en_compagnie_de(tokens: List[_Token], index: int) -> bool:
    before, after = _at(tokens, index - 1), _at(tokens, index + 1)
    return (
        before is not None
        and before.folded == "en"
        and after is not None
        and after.folded in _AFTER_EN_COMPAGNIE
    )


def _names_follow(tokens: List[_Token], index: int) -> bool:
    """Un mot à initiale capitale suit, après au plus un mot de liaison."""
    following = _at(tokens, index + 1)
    if following is not None and following.folded in _LINKING_WORDS:
        following = _at(tokens, index + 2)
    return (
        following is not None and following.capitalized and not following.text.isdigit()
    )


def _hit(tokens: List[_Token], index: int, ignored: frozenset) -> Optional[_Hit]:
    token = tokens[index]
    folded = token.folded
    if folded in ignored or folded.rstrip(".") in ignored:
        return None
    if token.text in LEGAL_FORMS:
        previous = _at(tokens, index - 1)
        strong = previous is not None and previous.capitalized
        return _Hit(
            token.start, token.end, folded, OrganizationType.COMPANY.value, strong
        )
    found = ESTABLISHMENT_WORDS.get(folded)
    if found is None:
        return None
    guessed = found.value
    if folded == "compagnie":
        if _is_en_compagnie_de(tokens, index):
            return None
        following = _at(tokens, index + 1)
        if following is not None and following.text.isdigit():
            guessed = OrganizationType.MILITARY.value
    strong = (
        folded in COMPANY_NAME_TRIGGERS
        and token.capitalized
        and _names_follow(tokens, index)
    )
    return _Hit(token.start, token.end, folded, guessed, strong)


def _widen(text: str, start: int, end: int) -> Tuple[int, int]:
    """Fenêtre autour d'un déclencheur, élargie aux limites de mots."""
    left = max(0, start - EXCERPT_RADIUS)
    right = min(len(text), end + EXCERPT_RADIUS)
    wide_left, wide_right = left, right
    while wide_left > 0 and not text[wide_left - 1].isspace():
        wide_left -= 1
    while wide_right < len(text) and not text[wide_right].isspace():
        wide_right += 1
    if wide_right - wide_left <= EXCERPT_MAX:
        return wide_left, wide_right
    return left, right


def _lead(text: str, start: int, end: int, hits: List[_Hit]) -> NoteLead:
    words: List[str] = []
    for h in hits:
        if h.word not in words:
            words.append(h.word)
    return NoteLead(
        start=start,
        end=end,
        words=tuple(words),
        guessed_type=hits[0].type,
        strong=any(h.strong for h in hits),
        excerpt=" ".join(text[start:end].split()),
    )


def find_note_leads(text: str, ignored_words: Iterable[str] = ()) -> List[NoteLead]:
    """Pistes d'une note, dans l'ordre du texte ; ``[]`` si aucune."""
    clean = _URL_RE.sub(lambda m: " " * len(m.group()), text)
    ignored = frozenset(_fold(w).strip() for w in ignored_words)
    tokens = _tokens(clean)
    hits = [h for h in (_hit(tokens, i, ignored) for i in range(len(tokens))) if h]
    leads: List[NoteLead] = []
    group: List[_Hit] = []
    start = end = 0
    for h in hits:
        left, right = _widen(clean, h.start, h.end)
        if group and left <= end and max(end, right) - start <= EXCERPT_MAX:
            group.append(h)
            end = max(end, right)
            continue
        if group:
            leads.append(_lead(clean, start, end, group))
        group, start, end = [h], left, right
    if group:
        leads.append(_lead(clean, start, end, group))
    return leads
