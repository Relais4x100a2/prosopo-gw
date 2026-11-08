"""Source interface: query, candidate and error types shared by all place sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from prosopo_gw_atelier.places.levels import Level


@dataclass(frozen=True)
class LevelQuery:
    """What is asked of a source: a place name with its written context."""

    name: str
    type: str | None = None
    parents: tuple[str, ...] = ()
    country: str | None = None
    department: str | None = None
    insee: str | None = None

    def key(self) -> str:
        """Stable cache key: sorted JSON of the fields."""
        return json.dumps(
            {
                "name": self.name.strip().casefold(),
                "type": self.type,
                "parents": [p.strip().casefold() for p in self.parents],
                "country": self.country,
                "department": self.department,
                "insee": self.insee,
            },
            sort_keys=True,
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class SourceCandidate:
    """A place proposed by a source."""

    source: str
    identifier: str
    name: str
    type: str | None = None
    parents: tuple[Level, ...] = ()
    start: str | None = None
    end: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    link: str | None = None
    insee: str | None = None


class SourceError(Exception):
    """Failure of a source; the message is French and can be shown as is."""


class Source(Protocol):
    name: str

    def search(self, query: LevelQuery) -> list[SourceCandidate]: ...

    def article(self, identifier: str) -> SourceCandidate | None: ...

    def covers(self, query: LevelQuery) -> bool:
        """Local coverage only (the API is an internal mode of the source)."""
        ...

    def can_answer(self, query: LevelQuery) -> bool:
        """Whether ``search`` can give a real answer now (local data or API)."""
        ...
