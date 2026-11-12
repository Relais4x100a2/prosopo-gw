"""Source interface: query, candidate and error types shared by all place sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Protocol

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
    # "upper": a written level above level 0, asked only to know the divisions of
    # the country (GeoNames); "level": the level being read.
    role: Literal["level", "upper"] = "level"

    def key(self) -> str:
        """Stable cache key: sorted JSON of the fields."""
        fields: dict[str, object] = {
            "name": self.name.strip().casefold(),
            "type": self.type,
            "parents": [p.strip().casefold() for p in self.parents],
            "country": self.country,
            "department": self.department,
            "insee": self.insee,
        }
        if self.role != "level":  # the default keeps the keys already stored
            fields["role"] = self.role
        return json.dumps(
            fields,
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
    source_text: str | None = None  # citation, e.g. "GeoNames 2026-11-08"
    population: int | None = None  # to order homonyms (GeoNames)
    feature_code: str | None = None  # GeoNames feature code, e.g. PPLA, ADM1
    role: Literal["level", "upper"] = "level"  # role of the query that found it
    asked: str | None = None  # written name an "upper" query searched (GeoNames)


class SourceError(Exception):
    """Failure of a source; the message is French and can be shown as is."""


class PermanentSourceError(SourceError):
    """A failure that retrying cannot fix (e.g. HTTP 404): the job fails at once."""


class CredentialsRejected(SourceError):
    """The source refuses the account (GeoNames code 10: unknown user or web
    service not enabled). Nothing can be asked until the user name changes: the
    worker holds the source's ``match`` jobs instead of failing them."""


class QuotaReached(SourceError):
    """A source quota is exhausted: nothing can be asked before ``retry_at``
    (a POSIX timestamp). The worker pauses the source instead of failing the job."""

    def __init__(self, message: str, retry_at: float) -> None:
        super().__init__(message)
        self.retry_at = retry_at


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
