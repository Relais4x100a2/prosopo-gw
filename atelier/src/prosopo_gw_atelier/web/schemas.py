"""Request and response bodies of the local API (JSON keys in English).

Writings travel only in bodies, never in a URL path: they hold any character
(``/``, ``?``, ``#``, quotes…).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..places.cluster import Confidence
from ..places.model import ElementKind
from ..project import ClusterState
from ..store.registry import Origin, Status


class Counts(BaseModel):
    total: int
    todo: int
    validated: int
    rejected: int
    already_decided: int


class ProjectInfo(BaseModel):
    gw_name: str
    gw_changed: bool
    counts: Counts
    cog_vintage: str
    postal_vintage: str


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
    proposal: dict[ElementKind, str]
    origins: dict[ElementKind, Origin]
    complements: list[Complement]
    writings: list[WritingOut]


class ValidateIn(BaseModel):
    fields: dict[ElementKind, str]
    checked: list[str]


class ValidateOut(BaseModel):
    place_id: str
    split: ClusterSummary | None


class SplitIn(BaseModel):
    writings: list[str]


class RejectOut(BaseModel):
    writings: list[str]


class CorrectIn(BaseModel):
    field: ElementKind
    value: str


class PlaceOut(BaseModel):
    place_id: str
    fields: dict[ElementKind, str]
    origins: dict[ElementKind, Origin]


class OccurrencesIn(BaseModel):
    writing: str


class OccurrenceOut(BaseModel):
    subject: Literal["person", "family"] | None
    label: str
    kind: str
    kind_label: str
    date: str | None
    complement: str | None


UndoKind = Literal["validate", "split", "reject", "correct", "import", "resolve"]


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


class ResolveIn(BaseModel):
    writing: str
    keep: Literal["current", "incoming"]
