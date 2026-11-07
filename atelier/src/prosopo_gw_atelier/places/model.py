"""Data model of the places step: writings, occurrences, decomposed elements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ElementKind = Literal[
    "commune",
    "postal_code",
    "insee_code",
    "department",
    "region",
    "country",
    "former_name",
]


@dataclass(frozen=True)
class Element:
    """One recognised element of a writing.

    ``hint`` is the French label of the clue that recognised it, shown as is on
    the validation screen.
    """

    kind: ElementKind
    value: str
    hint: str


@dataclass(frozen=True)
class Occurrence:
    """One non-empty place cell of a ``core`` table."""

    table: str
    row_id: str
    column: str
    complement: str | None
    event_type: str | None
    date: str | None


@dataclass
class Writing:
    """A distinct place writing (``parse_place(raw).name``) and its occurrences."""

    text: str
    occurrences: list[Occurrence] = field(default_factory=list)


@dataclass(frozen=True)
class Decomposition:
    """Result of decomposing a writing.

    ``insee`` is the commune resolved without ambiguity; ``candidates`` holds the
    possible INSEE codes (just ``(insee,)`` when resolved). ``ambiguous`` is set
    when a 5-character code is neither an INSEE code nor a postal code.
    """

    writing: str
    elements: tuple[Element, ...]
    insee: str | None
    candidates: tuple[str, ...]
    ambiguous: bool
