"""Request and response bodies of the local API (JSON keys in English).

Writings travel only in bodies, never in a URL path: they hold any character
(``/``, ``?``, ``#``, quotes…).

A place is a chain of levels (``LevelModel``, rank 0 = the most precise) and
a postal code; ``view`` is its French fixed-field view (``french_view``), read
only. Level types are open slugs: ``ProjectInfo.level_types`` lists the known
ones with their French labels, for the client's choice lists.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..places.cluster import Confidence
from ..places.levels import (
    HistoricalNature,
    LevelOrigin,
    LevelStatus,
    ViewField,
)
from ..places.model import ElementKind
from ..places.precision import PrecisionStatus
from ..project import ClusterState, ModeOrigin
from ..store.registry import SourceMode, Status


class Counts(BaseModel):
    total: int
    todo: int
    validated: int
    rejected: int
    already_decided: int


class LevelTypeOut(BaseModel):
    value: str
    label: str


class ProjectInfo(BaseModel):
    gw_name: str
    gw_changed: bool
    counts: Counts
    cog_vintage: str
    postal_vintage: str
    level_types: list[LevelTypeOut]


class LevelModel(BaseModel):
    """One level of a chain, in requests and responses.

    In a request, ``rank`` is ignored (levels are renumbered in the order
    given) and so is ``origin`` (the server derives it, see the validate
    route).
    """

    rank: int
    name: str
    written: str | None = None
    type: str | None = None
    identifier: str | None = None
    source: str | None = None
    start: str | None = None
    end: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    nature: HistoricalNature | None = None
    origin: LevelOrigin = "manual"
    status: LevelStatus = "validated"


class ClusterSummary(BaseModel):
    id: str
    label: str
    state: ClusterState
    confidence: Confidence
    occurrences: int
    parent_id: str | None
    provisional_name: str | None
    place_id: str | None
    writing_count: int


class ElementOut(BaseModel):
    kind: ElementKind
    value: str
    hint: str


class WritingOut(BaseModel):
    text: str
    occurrences: int
    hint: str
    elements: list[ElementOut]
    decided: Status | None


class Complement(BaseModel):
    text: str
    occurrences: int


class ClusterDetail(BaseModel):
    id: str
    label: str
    state: ClusterState
    confidence: Confidence
    occurrences: int
    parent_id: str | None
    provisional_name: str | None
    place_id: str | None
    levels: list[LevelModel]
    postal_code: str | None
    view: dict[ViewField, str]
    view_origins: dict[ViewField, LevelOrigin]
    from_registry: bool
    needs_manual_levels: bool
    alternatives: list[list[LevelModel]]
    historical_writings: dict[str, str]
    pending_sources: list[str]
    failed_sources: list[str]
    complements: list[Complement]
    writings: list[WritingOut]
    geonames_mode: SourceMode
    geonames_mode_origin: ModeOrigin


class ValidateIn(BaseModel):
    levels: list[LevelModel]
    postal_code: str | None
    checked: list[str]


class ValidateOut(BaseModel):
    place_id: str
    split: ClusterSummary | None


class SplitIn(BaseModel):
    writings: list[str]


class RejectOut(BaseModel):
    writings: list[str]


class LevelsIn(BaseModel):
    levels: list[LevelModel]
    postal_code: str | None


class PlaceOut(BaseModel):
    place_id: str
    levels: list[LevelModel]
    postal_code: str | None
    view: dict[ViewField, str]


class OccurrencesIn(BaseModel):
    writing: str


class OccurrenceOut(BaseModel):
    subject: Literal["person", "family"] | None
    label: str
    kind: str
    kind_label: str
    date: str | None
    complement: str | None


UndoKind = Literal[
    "validate", "split", "reject", "correct", "import", "resolve", "precision"
]


class UndoOut(BaseModel):
    action: UndoKind


class DecisionOut(BaseModel):
    status: Status
    place_id: str | None
    place_label: str | None


class ConflictOut(BaseModel):
    writing: str
    current: DecisionOut
    incoming: DecisionOut


class ConflictsOut(BaseModel):
    conflicts: list[ConflictOut]


class ImportOut(ConflictsOut):
    """Import result: writings it added, and every pending conflict."""

    added: int


class ResolveIn(BaseModel):
    writing: str
    keep: Literal["current", "incoming"]


class JournalEntryOut(BaseModel):
    """One registry journal entry, summarized for display.

    ``action`` is the registry's code (``validate``, ``reject``, ``correct``,
    ``detach``, ``import``, ``undo``), except that an import entry settling
    a conflict is reported as ``resolve`` and a precision decision (a
    ``correct`` entry whose details have kind ``precision``) as ``precision``.
    ``writings`` holds at most
    ``JOURNAL_WRITINGS`` of the writings touched (sorted); ``writing_count``
    counts them all. ``place_id`` is the one place the entry is about, if
    any; ``place_label`` its current commune or former name.
    """

    entry_id: int
    at: str
    action: str
    undone: bool
    undone_entry: int | None
    writings: list[str]
    writing_count: int
    place_id: str | None
    place_label: str | None


class JournalOut(BaseModel):
    entries: list[JournalEntryOut]


class CandidateOut(BaseModel):
    """An arrondissement proposed for a precision group.

    ``arrondissement`` is its French name (``None`` for "no arrondissement",
    i.e. an empty ``arrondissement_id``); ``clue`` is ``code``, ``number``,
    ``street`` or ``manual``.
    """

    arrondissement_id: str
    arrondissement: str | None
    quartier_id: str | None
    quartier: str | None
    clue: str


class PrecisionGroupOut(BaseModel):
    """Occurrences sharing a decision key; ``period_label`` is in French."""

    writing: str
    complement: str
    period: str
    period_label: str
    status: PrecisionStatus
    candidates: list[CandidateOut]
    occurrences: int


class PrecisionsOut(BaseModel):
    groups: list[PrecisionGroupOut]


class PrecisionDecideIn(BaseModel):
    """The user's choice; an empty or null ``arrondissement_id`` = none applies."""

    writing: str
    complement: str
    period: str
    arrondissement_id: str | None
    quartier_id: str | None


class PrecisionClearIn(BaseModel):
    """Identifies the group whose decision goes back to the computed status."""

    writing: str
    complement: str
    period: str


class PrecisionDecideOut(BaseModel):
    entry_id: int | None


class DicoTopoDepartment(BaseModel):
    code: str
    name: str
    downloaded_at: str
    articles: int
    skipped: int


class DicoTopoStatus(BaseModel):
    coverage: list[str]
    coverage_known: bool
    departments: list[DicoTopoDepartment]
    api_enabled: bool


class QueueError(BaseModel):
    source: str
    kind: str
    key: str
    error: str
    attempts: int


class QueueStatus(BaseModel):
    counts: dict[str, dict[str, int]]
    errors: list[QueueError]


class GeoNamesCountry(BaseModel):
    """An indexed country: ``downloaded_at`` is the extraction date of its file,
    ``size`` the bytes of the cached ``<CC>.zip`` (``None`` if it is gone)."""

    iso: str
    name: str
    downloaded_at: str
    size: int | None


class GeoNamesApi(BaseModel):
    """Requests counted today (UTC), end of the pause (ISO 8601 UTC) if any, and
    whether GeoNames refused the user name (requests held until it changes)."""

    today: int
    paused_until: str | None
    credentials_rejected: bool = False


class GeoNamesStatus(BaseModel):
    """Never the user name itself: only whether one is set."""

    countries: list[GeoNamesCountry]
    username_set: bool
    api: GeoNamesApi


class SourcesOut(BaseModel):
    dicotopo: DicoTopoStatus
    geonames: GeoNamesStatus
    queue: QueueStatus
    attributions: list[str]


class GeoNamesUsernameIn(BaseModel):
    username: str | None


class GeoNamesUsernameOut(BaseModel):
    username_set: bool


class CountryRowOut(BaseModel):
    """A foreign country of the project (``iso`` is ``None`` for a historical one);
    ``downloaded`` is the extraction date of its indexed GeoNames file;
    ``download`` the state of its download in the queue (``None``: no job)."""

    iso: str | None
    name: str
    writings: int
    occurrences: int
    mode: SourceMode
    downloaded: str | None
    download: Literal["queued", "running", "failed"] | None = None
    overrides: int


class CountriesOut(BaseModel):
    countries: list[CountryRowOut]


class ModeIn(BaseModel):
    """GeoNames mode sent by the client; checked by the route (400 if unknown).

    ``None`` removes a per-place correction (refused for a country)."""

    mode: str | None


class CountryModeOut(CountriesOut):
    """``queued``: the download of the country was put in the queue; ``size``: the
    announced size of ``<CC>.zip`` in bytes, when known."""

    iso: str
    mode: SourceMode
    queued: bool
    size: int | None


class GeoNamesSizeOut(BaseModel):
    """Announced size of ``<CC>.zip`` in bytes (``None`` if unknown)."""

    iso: str
    size: int | None


class DownloadIn(BaseModel):
    departments: list[str]


class DownloadOut(BaseModel):
    queued: list[str]


class CoverageRefreshOut(BaseModel):
    started: bool


class ApiToggleIn(BaseModel):
    enabled: bool


class ApiToggleOut(BaseModel):
    api_enabled: bool


class CacheClearIn(BaseModel):
    source: str


class CacheClearOut(BaseModel):
    cleared: str


class SourceProposalAcceptIn(BaseModel):
    level: LevelModel


class SourceProposalRefuseIn(BaseModel):
    subject: str
    source: str
    identifier: str


class SourceProposalRefuseOut(BaseModel):
    entry_id: int | None
