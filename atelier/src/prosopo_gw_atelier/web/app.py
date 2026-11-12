"""Local web server of the atelier: a JSON API over one project (design § 7).

The app serves one :class:`Project` and the personal :class:`PlaceRegistry`
to the browser of the same machine. Routes are listed in the task report and
in each function below; JSON keys are English, user-facing messages French.

Writings never appear in a URL path (they hold ``/``, ``?``, ``#``,
quotes…): they travel in JSON bodies. Cluster ids may be derived from a
writing (``name:<key>``, ``rejected:name:<key>``), so the cluster routes take the
id as a ``path`` parameter and the client percent-encodes it
(``encodeURIComponent``).

Concurrency
    FastAPI runs the (synchronous) endpoints in a thread pool. Project and
    registry are each thread-safe, but an action spans several calls (split
    then validate, then the undo stack): every endpoint that touches them
    holds ``AppState.lock``, so actions are serialized. The undo stack keeps
    the journal entry id each registry mutation returns, never the latest
    entry of the journal (another process may share the registry).

Undo
    A stack, in memory and per app, of actions; each action is a list of
    references ``("registry", entry_id)`` or ``("project", split_id)`` in the
    order they were done, undone in reverse order (registry entries with
    ``PlaceRegistry.undo``, splits with ``Project.unsplit``). An action whose
    undo fails (a later decision changed the same rows) is dropped from the
    stack and reported with 409.

Security (local app)
    ``TrustedHostMiddleware`` accepts only ``127.0.0.1`` and ``localhost``
    (DNS rebinding); a state-changing request (any method but GET, HEAD,
    OPTIONS) carrying an ``Origin`` header other than
    ``http://127.0.0.1[:port]`` or ``http://localhost[:port]`` gets 403
    (cross-site requests from other pages). No CORS headers are sent.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from geneweb_py.formats.table_writers import base_stem
from geneweb_py.formats.tables import EVENT_TYPE_LABELS, Table
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..export.archive import build_archive
from ..places.cluster import name_key
from ..places.levels import (
    FOREIGN_TYPES,
    FRENCH_TYPES,
    TYPE_LABELS,
    Level,
    LevelOrigin,
    check_chain,
    french_view,
    renumber,
    view_origins,
)
from ..places.model import Occurrence
from ..places.precision import PrecisionStatus
from ..project import ClusterState, ClusterView, PrecisionGroup, Project
from ..refdata import RefData
from ..refdata.arrondissements import name_of
from ..sources import DICOTOPO, GEONAMES, SourceRuntime
from ..sources.base import SourceError
from ..sources.dicotopo.download import remove_department, request_download
from ..sources.geonames.download import (
    country_size,
    download_state,
    remove_country,
    request_country,
    retry_country,
)
from ..store.exchange import (
    Conflict,
    RegistryFormatError,
    StaleConflictError,
    export_registry,
    import_registry,
    resolve_conflict,
)
from ..store.registry import JournalEntry, Place, PlaceRegistry, SourceMode
from . import schemas

MAX_IMPORT_BYTES = 50 * 1024 * 1024
"""Largest registry file accepted by the import (413 beyond)."""

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
_LOCAL_ORIGIN = re.compile(r"^http://(?:127\.0\.0\.1|localhost)(?::\d{1,5})?$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_PAGE_CSP = (
    "default-src 'self'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
"""The page loads only its own files: no inline script, nothing remote."""
_IMPORT_PATH = "/api/registry/import"
IMPORT_FORMAT_ERROR = "Le fichier n'est pas un export de référentiel valide."
JOURNAL_WRITINGS = 20
"""Writings listed per journal entry (``writing_count`` counts them all)."""

_FIXED_KINDS = {
    "naissance": ("birth", "Naissance"),
    "deces": ("death", "Décès"),
    "mariage": ("marriage", "Mariage"),
}

ATTRIBUTIONS = [
    "DicoTopo : dictionnaire topographique de la France, École nationale des "
    "chartes et Comité des travaux historiques et scientifiques (CTHS), "
    "licence CC BY-NC-ND 3.0 FR (usage non commercial, sans modification).",
    "Source et conditions : https://github.com/chartes/dico-topo",
    "GeoNames (https://www.geonames.org/), licence CC BY 4.0 : fichiers par pays "
    "et service web, téléchargés à la demande.",
]
"""Credits shown on the Sources screen."""

_SOURCES_OFF = "Les sources externes ne sont pas disponibles."

_SOURCE_ORIGINS: frozenset[str] = frozenset({DICOTOPO, GEONAMES})
"""Origins of the levels a source proposes (laid over a chain, never saved as is)."""

_SOURCE_MODES: tuple[SourceMode, ...] = get_args(SourceMode)
_GEONAMES_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_USERNAME_INVALID = (
    "Identifiant GeoNames invalide : lettres, chiffres, « _ », « - » et « . » "
    "seulement (100 caractères au plus)."
)
_MODE_INVALID = (
    "Mode GeoNames inconnu : « written » (garder tel qu'écrit) ou « geonames » "
    "(proposer avec GeoNames) attendu."
)

RefKind = Literal["registry", "project"]


@dataclass(frozen=True)
class _Ref:
    kind: RefKind
    value: int | str


@dataclass(frozen=True)
class _Action:
    kind: schemas.UndoKind
    refs: tuple[_Ref, ...]


@dataclass
class _Labels:
    """Labels of persons and families, and the subject of each event."""

    tables_id: int
    persons: dict[str, str]
    families: dict[str, str]
    events: dict[str, tuple[Literal["person", "family"], str]]


@dataclass
class AppState:
    project: Project
    registry: PlaceRegistry
    ref: RefData
    lock: threading.RLock = field(default_factory=threading.RLock)
    undo: list[_Action] = field(default_factory=list)
    conflicts: dict[str, Conflict] = field(default_factory=dict)
    labels: _Labels | None = None
    sources: SourceRuntime | None = None


_PERIOD_LABELS = {
    "paris-1795": "avant 1860",
    "paris-1860": "depuis 1860",
    "lyon": "Lyon",
    "marseille": "Marseille",
    "": "sans date",
}


def _precision_group(group: PrecisionGroup) -> schemas.PrecisionGroupOut:
    return schemas.PrecisionGroupOut(
        writing=group.writing,
        complement=group.complement,
        period=group.period,
        period_label=_PERIOD_LABELS.get(group.period, group.period),
        status=group.status,
        candidates=[
            schemas.CandidateOut(
                arrondissement_id=c.arrondissement_id,
                arrondissement=name_of(c.arrondissement_id)
                if c.arrondissement_id
                else None,
                quartier_id=c.quartier_id,
                quartier=c.quartier,
                clue=c.clue,
            )
            for c in group.candidates
        ],
        occurrences=group.occurrences,
    )


# -- helpers -------------------------------------------------------------------


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def _label(view: ClusterView) -> str:
    if view.provisional_name:
        return view.provisional_name
    name = _chain_name(view.cluster.levels, view.cluster.postal_code)
    if name:
        return name
    return view.cluster.writings[0] if view.cluster.writings else view.cluster.id


def _chain_name(levels: Sequence[Level], postal_code: str | None) -> str | None:
    """Name of a chain: its historical commune, else its commune, else its most
    precise level, whatever its status (a level a source proposes in place of a
    written one gives its written form, else its name).

    A commune split into arrondissements is followed by the short name of its
    arrondissement (``Paris 16e``), so that its places read apart in the list."""
    view = french_view(levels, postal_code)
    name = view.get("historical_commune") or view.get("commune")
    if name:
        district = next(
            (level for level in levels if level.type == "arrondissement"), None
        )
        if district is None:
            return name
        short = district.name.strip().removesuffix(" arrondissement").strip()
        return f"{name} {short or district.name.strip()}"
    finest = min(levels, key=lambda level: level.rank, default=None)
    if finest is None:
        return None
    if finest.status == "validated":
        return finest.name
    return finest.written or finest.name


def _level_out(level: Level) -> schemas.LevelModel:
    return schemas.LevelModel(
        rank=level.rank,
        name=level.name,
        written=level.written,
        type=level.type,
        identifier=level.identifier,
        source=level.source,
        start=level.start,
        end=level.end,
        latitude=level.latitude,
        longitude=level.longitude,
        nature=level.nature,
        origin=level.origin,
        status=level.status,
    )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _levels_in(
    sent: Sequence[schemas.LevelModel], known: Sequence[Level]
) -> tuple[Level, ...]:
    """Levels of a request, renumbered, with their origins derived.

    A level identical (same name, type and identifier) to one of ``known``
    keeps that level's origin; any other level is ``manual``. The client's
    ranks and origins are ignored.
    """
    origins = {(lv.name, lv.type, lv.identifier): lv.origin for lv in known}
    levels = []
    for model in sent:
        level = Level(
            rank=model.rank,
            name=model.name.strip(),
            written=_blank_to_none(model.written),
            type=_blank_to_none(model.type),
            identifier=_blank_to_none(model.identifier),
            source=_blank_to_none(model.source),
            start=_blank_to_none(model.start),
            end=_blank_to_none(model.end),
            latitude=model.latitude,
            longitude=model.longitude,
            nature=model.nature,
            status=model.status,
        )
        origin = origins.get((level.name, level.type, level.identifier), "manual")
        levels.append(replace(level, origin=origin))
    return renumber(levels)


_PROPOSAL_GONE = (
    "Ce niveau n'est plus une proposition : il a changé entre-temps ; "
    "rechargez le lieu."
)
"""409 of accept/refuse when the registry no longer holds the proposal."""


def _checked_levels(
    sent: Sequence[schemas.LevelModel], known: Sequence[Level]
) -> tuple[Level, ...]:
    """:func:`_levels_in`, then :func:`check_chain` (400 with its message).

    A chain sent by the user must also hold a validated level (400): only
    recorded data, such as a migrated place, may hold proposals alone.
    """
    levels = _levels_in(sent, known)
    try:
        check_chain(levels)
    except ValueError as exc:
        raise _error(400, str(exc)) from None
    if not any(level.status == "validated" for level in levels):
        raise _error(400, "La chaîne doit contenir au moins un niveau validé.")
    return levels


def _strip_overlay(levels: Sequence[Level], view: ClusterView) -> tuple[Level, ...]:
    """``levels`` without the sources' proposals laid over the chain.

    A level proposed by a source (origin ``dicotopo`` or ``geonames``, status
    ``proposed``, absent from ``view.base_levels``) is not saved: the written level
    it made precise (same name or written form, untyped) comes back in its place;
    without such a level, it is dropped. The other proposed levels (recorded ones)
    are kept.
    """
    base = {(lv.name, lv.type, lv.identifier) for lv in view.base_levels}
    out: list[Level] = []
    for level in levels:
        overlay = (
            level.status == "proposed"
            and level.origin in _SOURCE_ORIGINS
            and (level.name, level.type, level.identifier) not in base
        )
        if not overlay:
            out.append(level)
            continue
        names = {name_key(n) for n in (level.name, level.written) if n}
        original = next(
            (
                lv
                for lv in view.base_levels
                if lv.type is None
                and name_key(lv.name) in names
                and (lv.name, lv.type, lv.identifier)
                not in {(o.name, o.type, o.identifier) for o in out}
            ),
            None,
        )
        if original is not None:
            out.append(original)
    return renumber(out)


def _postal_in(
    sent: str | None, known: str | None, known_origin: LevelOrigin | None
) -> tuple[str | None, LevelOrigin | None]:
    """Postal code of a request and its origin: kept if unchanged, else manual."""
    postal = _blank_to_none(sent)
    if postal is None:
        return None, None
    if postal == known and known_origin is not None:
        return postal, known_origin
    return postal, "manual"


def _place_out(place: Place) -> schemas.PlaceOut:
    return schemas.PlaceOut(
        place_id=place.place_id,
        levels=[_level_out(level) for level in place.levels],
        postal_code=place.postal_code,
        view=place.fields,
    )


def _summary(view: ClusterView) -> schemas.ClusterSummary:
    return schemas.ClusterSummary(
        id=view.cluster.id,
        label=_label(view),
        state=view.state,
        confidence=view.cluster.confidence,
        occurrences=view.occurrences,
        parent_id=view.parent_id,
        provisional_name=view.provisional_name,
        place_id=view.place_id,
        writing_count=len(view.cluster.writings),
    )


def _hint(project: Project, writing: str) -> tuple[str, list[schemas.ElementOut]]:
    """Attachment hint of a writing: the clues its decomposition recognised.

    The distinct hints of its elements in the order written, joined by
    `` + `` ("code postal + nom"); "aucun indice reconnu" when there is none.
    ``code ambigu`` is added for a 5-character code that is neither an INSEE
    nor a postal code, ``plusieurs communes possibles`` when the commune is
    not resolved but several are candidates.
    """
    decomposition = project.decomposition(writing)
    hints = list(dict.fromkeys(e.hint for e in decomposition.elements))
    if decomposition.ambiguous:
        hints.append("code ambigu")
    if decomposition.insee is None and len(decomposition.candidates) > 1:
        hints.append("plusieurs communes possibles")
    elements = [
        schemas.ElementOut(kind=e.kind, value=e.value, hint=e.hint)
        for e in decomposition.elements
    ]
    return (" + ".join(hints) or "aucun indice reconnu"), elements


def _detail(state: AppState, view: ClusterView) -> schemas.ClusterDetail:
    project, registry = state.project, state.registry
    writings = view.cluster.writings
    decisions = registry.decisions(writings)
    complements: Counter[str] = Counter()
    rows = []
    for text in writings:
        occurrences = project.writings[text].occurrences
        complements.update(o.complement for o in occurrences if o.complement)
        hint, elements = _hint(project, text)
        decision = decisions.get(text)
        rows.append(
            schemas.WritingOut(
                text=text,
                occurrences=len(occurrences),
                hint=hint,
                elements=elements,
                decided=decision.status if decision else None,
            )
        )
    levels = view.cluster.levels
    postal_code = view.cluster.postal_code
    summary = _summary(view)
    return schemas.ClusterDetail(
        id=summary.id,
        label=summary.label,
        state=summary.state,
        confidence=summary.confidence,
        occurrences=summary.occurrences,
        parent_id=summary.parent_id,
        provisional_name=summary.provisional_name,
        place_id=summary.place_id,
        levels=[_level_out(level) for level in levels],
        postal_code=postal_code,
        view=french_view(levels, postal_code),
        view_origins=view_origins(levels),
        from_registry=view.from_registry,
        needs_manual_levels=view.needs_manual_levels,
        alternatives=[
            [_level_out(level) for level in chain]
            for chain in view.cluster.alternatives
        ],
        historical_writings=dict(view.historical_writings),
        pending_sources=list(view.pending_sources),
        failed_sources=list(view.failed_sources),
        complements=[
            schemas.Complement(text=text, occurrences=count)
            for text, count in sorted(complements.items(), key=lambda i: (-i[1], i[0]))
        ],
        writings=rows,
        geonames_mode=view.geonames_mode,
        geonames_mode_origin=view.geonames_mode_origin,
    )


def _person_label(row: Mapping[str, object]) -> str:
    parts = [str(row.get(k) or "").strip() for k in ("prenom", "nom")]
    return " ".join(p for p in parts if p) or str(row.get("personne_id") or "?")


def _labels(state: AppState) -> _Labels:
    tables: list[Table] = state.project.tables
    if state.labels is not None and state.labels.tables_id == id(tables):
        return state.labels
    by_name = {table.spec.name: table for table in tables}
    persons: dict[str, str] = {}
    for row in by_name["personnes"].rows if "personnes" in by_name else []:
        persons[str(row["personne_id"])] = _person_label(row)
    families: dict[str, str] = {}
    for row in by_name["familles"].rows if "familles" in by_name else []:
        spouses = [
            persons.get(str(row[k]), str(row[k]))
            for k in ("mari_id", "femme_id")
            if row.get(k)
        ]
        families[str(row["famille_id"])] = " × ".join(spouses) or str(row["famille_id"])
    events: dict[str, tuple[Literal["person", "family"], str]] = {}
    for row in by_name["evenements"].rows if "evenements" in by_name else []:
        if row.get("personne_id"):
            events[str(row["evenement_id"])] = ("person", str(row["personne_id"]))
        elif row.get("famille_id"):
            events[str(row["evenement_id"])] = ("family", str(row["famille_id"]))
    state.labels = _Labels(id(tables), persons, families, events)
    return state.labels


def _occurrence(labels: _Labels, occurrence: Occurrence) -> schemas.OccurrenceOut:
    subject: Literal["person", "family"] | None = None
    label = occurrence.row_id
    if occurrence.table == "personnes":
        subject, label = "person", labels.persons.get(occurrence.row_id, label)
    elif occurrence.table == "familles":
        subject, label = "family", labels.families.get(occurrence.row_id, label)
    elif occurrence.row_id in labels.events:
        subject, target = labels.events[occurrence.row_id]
        names = labels.persons if subject == "person" else labels.families
        label = names.get(target, target)
    code = occurrence.event_type or ""
    if occurrence.table != "evenements" and code in _FIXED_KINDS:
        kind, kind_label = _FIXED_KINDS[code]
    else:
        kind, kind_label = code, EVENT_TYPE_LABELS.get(code, code)
    return schemas.OccurrenceOut(
        subject=subject,
        label=label,
        kind=kind,
        kind_label=kind_label,
        date=occurrence.date,
        complement=occurrence.complement,
    )


def _place_label(place: Place | None) -> str | None:
    if place is None:
        return None
    return _chain_name(place.levels, place.postal_code)


def _known_place(registry: PlaceRegistry, place_id: str | None) -> Place | None:
    if place_id is None:
        return None
    try:
        return registry.place(place_id)
    except KeyError:
        return None


def _conflicts(state: AppState) -> schemas.ConflictsOut:
    registry = state.registry
    out = []
    for writing in sorted(state.conflicts):
        conflict = state.conflicts[writing]
        current = conflict.current
        incoming = conflict.incoming
        incoming_place = _known_place(registry, incoming.place_id)
        if incoming_place is None:
            incoming_place = conflict.incoming_place
        out.append(
            schemas.ConflictOut(
                writing=writing,
                current=schemas.DecisionOut(
                    status=current.status,
                    place_id=current.place_id,
                    place_label=_place_label(_known_place(registry, current.place_id)),
                ),
                incoming=schemas.DecisionOut(
                    status=incoming.status,
                    place_id=incoming.place_id,
                    place_label=_place_label(incoming_place),
                ),
            )
        )
    return schemas.ConflictsOut(conflicts=out)


def _journal_place(rows: Sequence[Mapping[str, Any]], details: object) -> str | None:
    """The one place a journal entry is about, or None (none or several)."""
    if isinstance(details, Mapping) and isinstance(details.get("place_id"), str):
        return str(details["place_id"])
    ids: set[str] = set()
    for row in rows:
        if row["table"] == "writings":
            row_state = row["after"] if row["after"] is not None else row["before"]
            if row_state and row_state.get("place_id"):
                ids.add(row_state["place_id"])
        elif "place_id" in row["key"]:  # precision rows are keyed by writing
            ids.add(row["key"]["place_id"])
    return ids.pop() if len(ids) == 1 else None


def _journal_entry(
    registry: PlaceRegistry, entry: JournalEntry
) -> schemas.JournalEntryOut:
    payload = entry.payload
    rows: list[Mapping[str, Any]] = payload.get("rows", [])
    details = payload.get("details")
    writings = sorted(
        {row["key"]["writing"] for row in rows if row["table"] == "writings"}
    )
    action = entry.action
    if (
        action == "import"
        and isinstance(details, Mapping)
        and "resolved_conflict" in details
    ):
        action = "resolve"
    if (
        action == "correct"
        and isinstance(details, Mapping)
        and details.get("kind") == "precision"
    ):
        action = "precision"
    undone_entry = payload.get("undone_entry") if action == "undo" else None
    place_id = _journal_place(rows, details)
    return schemas.JournalEntryOut(
        entry_id=entry.entry_id,
        at=entry.at,
        action=action,
        undone=entry.undone,
        undone_entry=undone_entry if isinstance(undone_entry, int) else None,
        writings=writings[:JOURNAL_WRITINGS],
        writing_count=len(writings),
        place_id=place_id,
        place_label=_place_label(_known_place(registry, place_id)),
    )


def _journal_writing_count(registry: PlaceRegistry, entry_id: int) -> int:
    """Distinct writings touched by journal entry ``entry_id`` (the newest)."""
    for entry in registry.journal(limit=1):
        if entry.entry_id == entry_id:
            rows: list[Mapping[str, Any]] = entry.payload.get("rows", [])
            return len(
                {row["key"]["writing"] for row in rows if row["table"] == "writings"}
            )
    return 0


def _attachment(filename: str) -> str:
    fallback = filename.encode("ascii", "replace").decode("ascii")
    fallback = fallback.replace("?", "_").replace('"', "_").replace("\\", "_")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def _project_info(state: AppState) -> schemas.ProjectInfo:
    views = state.project.clusters()
    counts: Counter[ClusterState] = Counter(view.state for view in views)
    return schemas.ProjectInfo(
        gw_name=state.project.gw_path.name,
        gw_changed=state.project.gw_changed,
        counts=schemas.Counts(
            total=len(views),
            todo=counts["todo"],
            validated=counts["validated"],
            rejected=counts["rejected"],
            already_decided=counts["already_decided"],
        ),
        cog_vintage=state.ref.cog_vintage,
        postal_vintage=state.ref.postal_vintage,
        level_types=[
            schemas.LevelTypeOut(value=value, label=TYPE_LABELS[value])
            for value in (*FRENCH_TYPES, *FOREIGN_TYPES)
        ],
    )


class _UndoFailed(Exception):
    """An undo stopped on a ref; ``remaining`` are the refs not undone yet."""

    def __init__(self, remaining: tuple[_Ref, ...], cause: Exception) -> None:
        super().__init__(str(cause))
        self.remaining = remaining
        self.cause = cause


def _undo_refs(state: AppState, refs: Sequence[_Ref]) -> None:
    """Undo ``refs`` in reverse order.

    Stops at the first ref that cannot be undone (registry ``ValueError``,
    unknown split ``KeyError``) and raises ``_UndoFailed`` with the refs not
    undone yet, that one included, in their original order.
    """
    for index in range(len(refs) - 1, -1, -1):
        ref = refs[index]
        try:
            if ref.kind == "registry":
                assert isinstance(ref.value, int)
                state.registry.undo(ref.value)
            else:
                assert isinstance(ref.value, str)
                state.project.unsplit(ref.value)
        except (ValueError, KeyError) as exc:
            raise _UndoFailed(tuple(refs[: index + 1]), exc) from exc


def _cluster_or_404(project: Project, cluster_id: str) -> ClusterView:
    try:
        return project.cluster(cluster_id)
    except KeyError:
        raise _error(404, "Ce lieu n'existe pas (ou plus) dans la file.") from None


def _split_out(
    state: AppState, view: ClusterView, writings: Sequence[str]
) -> tuple[list[_Ref], str]:
    """Take ``writings`` out of ``view`` into a new cluster; detach their decisions.

    Writings taken out leave the place they were attached to: their registry
    decisions (if any) are removed, so the new cluster is to be decided.
    Returns the references done (split first, then the detach entry) and the
    id of the new cluster.
    """
    project, registry = state.project, state.registry
    try:
        new = project.split(view.cluster.id, writings)
    except ValueError as exc:
        raise _error(400, f"Sortie impossible : {exc}") from None
    refs = [_Ref("project", new.cluster.id)]
    decided = list(registry.decisions(writings))
    if decided:
        try:
            entry = registry.detach(decided, project.project_id)
        except BaseException:
            _undo_refs(state, refs)
            raise
        if entry is not None:
            refs.append(_Ref("registry", entry))
    return refs, new.cluster.id


# -- app -----------------------------------------------------------------------


def create_app(
    project: Project,
    registry: PlaceRegistry,
    ref: RefData,
    *,
    sources: SourceRuntime | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """The atelier's web app over ``project`` and ``registry``.

    With ``sources`` the project is attached to the source queue; the worker
    thread runs between the app's startup and shutdown only if ``start_worker``
    (tests pass ``False`` and drive ``sources.worker.run_once()``).
    """
    state = AppState(project, registry, ref, sources=sources)

    def reattach() -> None:
        """(Re)connect the project to the sources: they or their data changed."""
        if sources is not None:
            project.attach_sources(
                sources.queue, sources.sources, geonames_index=sources.geonames_index
            )

    reattach()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if sources is not None and start_worker:
            sources.start()
        try:
            yield
        finally:
            if sources is not None:
                sources.stop()

    app = FastAPI(
        title="Atelier prosopo-gw",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.atelier = state

    @app.middleware("http")
    async def check_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and not _LOCAL_ORIGIN.fullmatch(origin):
                return JSONResponse(
                    {"detail": "Requête refusée : elle ne vient pas de l'atelier."},
                    status_code=403,
                )
            if request.url.path == _IMPORT_PATH:
                length = request.headers.get("content-length", "")
                if length.isdigit() and int(length) > MAX_IMPORT_BYTES + 65536:
                    return JSONResponse(
                        {"detail": "Fichier trop volumineux (50 Mo au plus)."},
                        status_code=413,
                    )
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            # Revalidate the page and its files (ETag) so that an upgraded
            # package is picked up without a forced reload.
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # Added last, so outermost: the host is checked before anything else.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])} : {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse(
            {"detail": f"Requête invalide ({problems})."}, status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if exc.status_code == 404 and detail == "Not Found":
            detail = "Ressource introuvable."
        elif exc.status_code == 405 and detail == "Method Not Allowed":
            detail = "Méthode non autorisée."
        return JSONResponse(
            {"detail": detail}, status_code=exc.status_code, headers=exc.headers
        )

    # -- page ---------------------------------------------------------------

    @app.get("/", response_class=FileResponse)
    def index() -> FileResponse:
        return FileResponse(
            _STATIC_DIR / "index.html",
            media_type="text/html",
            headers={"Content-Security-Policy": _PAGE_CSP},
        )

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # -- project ------------------------------------------------------------

    @app.get("/api/project")
    def get_project() -> schemas.ProjectInfo:
        with state.lock:
            return _project_info(state)

    @app.post("/api/project/reload")
    def reload_project() -> schemas.ProjectInfo:
        with state.lock:
            try:
                project.reload()
            except OSError as exc:
                raise _error(
                    409, f"Impossible de relire {project.gw_path.name} : {exc}"
                ) from None
            return _project_info(state)

    # -- clusters -----------------------------------------------------------

    @app.get("/api/clusters")
    def list_clusters(
        wanted: ClusterState | None = Query(None, alias="state"),
    ) -> list[schemas.ClusterSummary]:
        with state.lock:
            views = project.clusters()
        return [_summary(v) for v in views if wanted is None or v.state == wanted]

    @app.get("/api/clusters/{cluster_id:path}")
    def get_cluster(cluster_id: str) -> schemas.ClusterDetail:
        with state.lock:
            _cluster_or_404(project, cluster_id)
            project.touch(cluster_id)
            return _detail(state, _cluster_or_404(project, cluster_id))

    @app.post("/api/clusters/{cluster_id:path}/validate")
    def validate_cluster(
        cluster_id: str, body: schemas.ValidateIn
    ) -> schemas.ValidateOut:
        with state.lock:
            view = _cluster_or_404(project, cluster_id)
            members = view.cluster.writings
            checked = list(dict.fromkeys(body.checked))
            if not checked:
                raise _error(400, "Cochez au moins une écriture à valider.")
            unknown = [w for w in checked if w not in members]
            if unknown:
                raise _error(
                    400, f"Écritures absentes de ce lieu : {', '.join(unknown)}."
                )
            # Checked before any split: a rejected chain leaves nothing done.
            levels = _checked_levels(body.levels, view.cluster.levels)
            levels = _strip_overlay(levels, view)
            if not any(level.status == "validated" for level in levels):
                raise _error(400, "La chaîne doit contenir au moins un niveau validé.")
            place_id = view.place_id if view.from_registry else None
            known_origin: LevelOrigin | None = "written"
            if place_id is not None:
                try:
                    known_origin = registry.place(place_id).postal_origin
                except KeyError:
                    raise _error(
                        409, "Ce lieu a été supprimé entre-temps ; rechargez la file."
                    ) from None
            postal, postal_origin = _postal_in(
                body.postal_code, view.cluster.postal_code, known_origin
            )
            refs: list[_Ref] = []
            split_id: str | None = None
            unchecked = [w for w in members if w not in checked]
            if unchecked:
                refs, split_id = _split_out(state, view, unchecked)
            try:
                validation = registry.validate(
                    checked, levels, postal, postal_origin, project.project_id, place_id
                )
            except BaseException as exc:
                _undo_refs(state, refs)
                if isinstance(exc, KeyError):
                    raise _error(
                        409, "Ce lieu a été supprimé entre-temps ; rechargez la file."
                    ) from None
                raise
            if validation.entry_id is not None:
                refs.append(_Ref("registry", validation.entry_id))
            if refs:
                state.undo.append(_Action("validate", tuple(refs)))
            split = None
            if split_id is not None:
                split = _summary(project.cluster(split_id))
            return schemas.ValidateOut(place_id=validation.place_id, split=split)

    @app.post("/api/clusters/{cluster_id:path}/split")
    def split_cluster(cluster_id: str, body: schemas.SplitIn) -> schemas.ClusterSummary:
        with state.lock:
            view = _cluster_or_404(project, cluster_id)
            refs, split_id = _split_out(state, view, body.writings)
            state.undo.append(_Action("split", tuple(refs)))
            return _summary(project.cluster(split_id))

    @app.post("/api/clusters/{cluster_id:path}/reject")
    def reject_cluster(cluster_id: str) -> schemas.RejectOut:
        with state.lock:
            view = _cluster_or_404(project, cluster_id)
            writings = list(view.cluster.writings)
            entry = registry.reject(writings, project.project_id)
            if entry is not None:
                state.undo.append(_Action("reject", (_Ref("registry", entry),)))
            return schemas.RejectOut(writings=writings)

    # -- places -------------------------------------------------------------

    def _place_or_404(place_id: str) -> Place:
        try:
            return registry.place(place_id)
        except KeyError:
            raise _error(404, "Ce lieu n'existe pas dans le référentiel.") from None

    def _push_correct(entry: int | None, kind: schemas.UndoKind = "correct") -> None:
        if entry is not None:
            state.undo.append(_Action(kind, (_Ref("registry", entry),)))

    @app.put("/api/places/{place_id}/levels")
    def set_place_levels(place_id: str, body: schemas.LevelsIn) -> schemas.PlaceOut:
        """Replace the chain of a place (and its postal code)."""
        with state.lock:
            place = _place_or_404(place_id)
            levels = _checked_levels(body.levels, place.levels)
            postal, postal_origin = _postal_in(
                body.postal_code, place.postal_code, place.postal_origin
            )
            try:
                entry = registry.set_levels(
                    place_id, levels, postal, postal_origin, project.project_id
                )
            except KeyError:
                raise _error(404, "Ce lieu n'existe pas dans le référentiel.") from None
            except ValueError as exc:
                raise _error(400, str(exc)) from None
            _push_correct(entry)
            return _place_out(registry.place(place_id))

    def _proposal_or_error(place_id: str, rank: int) -> Place:
        place = _place_or_404(place_id)
        level = next((lv for lv in place.levels if lv.rank == rank), None)
        if level is None:
            raise _error(404, f"Ce lieu n'a pas de niveau de rang {rank}.")
        if level.status != "proposed":
            raise _error(409, f"Le niveau de rang {rank} n'est pas une proposition.")
        return place

    @app.post("/api/places/{place_id}/levels/{rank}/accept")
    def accept_level(place_id: str, rank: int) -> schemas.PlaceOut:
        """Validate a proposed level of a place."""
        with state.lock:
            _proposal_or_error(place_id, rank)
            try:
                entry = registry.accept_proposal(place_id, rank, project.project_id)
            except KeyError:
                raise _error(404, "Ce lieu n'existe pas dans le référentiel.") from None
            except ValueError:
                raise _error(409, _PROPOSAL_GONE) from None
            _push_correct(entry)
            return _place_out(registry.place(place_id))

    @app.post("/api/places/{place_id}/levels/{rank}/refuse")
    def refuse_level(place_id: str, rank: int) -> schemas.PlaceOut:
        """Remove a proposed level of a place."""
        with state.lock:
            place = _proposal_or_error(place_id, rank)
            if len(place.levels) == 1:
                raise _error(
                    409,
                    "Ce niveau est le seul du lieu : ajoutez-en un autre "
                    "avant de le refuser.",
                )
            try:
                entry = registry.refuse_proposal(place_id, rank, project.project_id)
            except KeyError:
                raise _error(404, "Ce lieu n'existe pas dans le référentiel.") from None
            except ValueError:
                raise _error(409, _PROPOSAL_GONE) from None
            _push_correct(entry)
            return _place_out(registry.place(place_id))

    # -- external sources ---------------------------------------------------

    def _runtime() -> SourceRuntime:
        if sources is None:
            raise _error(503, _SOURCES_OFF)
        return sources

    def _queue_status(runtime: SourceRuntime) -> schemas.QueueStatus:
        return schemas.QueueStatus(
            counts={
                name: {str(k): v for k, v in per.items()}
                for name, per in runtime.queue.counts().items()
            },
            errors=[
                schemas.QueueError(
                    source=job.source,
                    kind=job.kind,
                    key=job.key,
                    error=job.error or "",
                    attempts=job.attempts,
                )
                for job in runtime.queue.errors()
            ],
        )

    def _geonames_status(runtime: SourceRuntime) -> schemas.GeoNamesStatus:
        """Cache and queue only, never the network; never the user name."""
        paused = runtime.queue.paused_until(GEONAMES)
        return schemas.GeoNamesStatus(
            countries=[
                schemas.GeoNamesCountry(
                    iso=iso,
                    name=ref.country_of_iso(iso) or iso,
                    downloaded_at=extracted,
                    size=runtime.geonames_size(iso),
                )
                for iso, extracted in sorted(runtime.geonames_index.countries().items())
            ],
            username_set=bool(runtime.config.geonames_username),
            api=schemas.GeoNamesApi(
                today=runtime.geonames.requests_today(),
                paused_until=None
                if paused is None
                else datetime.fromtimestamp(paused, UTC).isoformat(timespec="seconds"),
                credentials_rejected=runtime.queue.credentials_rejected(GEONAMES),
            ),
        )

    @app.get("/api/sources")
    def get_sources() -> schemas.SourcesOut:
        runtime = _runtime()
        covered = runtime.coverage()  # cache only, never the network
        return schemas.SourcesOut(
            dicotopo=schemas.DicoTopoStatus(
                coverage=covered,
                coverage_known=bool(covered),
                departments=[
                    schemas.DicoTopoDepartment(
                        code=code,
                        name=ref.department_name(code) or "",
                        downloaded_at=at,
                        articles=articles,
                        skipped=skipped,
                    )
                    for code, at, articles, skipped in runtime.index.details()
                ],
                api_enabled=runtime.config.dicotopo_api,
            ),
            geonames=_geonames_status(runtime),
            queue=_queue_status(runtime),
            attributions=list(ATTRIBUTIONS),
        )

    @app.post("/api/sources/dicotopo/download")
    def download_dicotopo(body: schemas.DownloadIn) -> schemas.DownloadOut:
        runtime = _runtime()
        if not body.departments:
            raise _error(400, "Indiquez au moins un département à télécharger.")
        codes = list(dict.fromkeys(d.strip().upper() for d in body.departments))
        try:
            request_download(runtime.queue, codes, covered=runtime.coverage())
        except SourceError as exc:
            raise _error(400, str(exc)) from None
        return schemas.DownloadOut(queued=codes)

    @app.post("/api/sources/dicotopo/coverage/refresh")
    def refresh_dicotopo_coverage() -> schemas.CoverageRefreshOut:
        return schemas.CoverageRefreshOut(started=_runtime().refresh_coverage())

    @app.delete("/api/sources/dicotopo/departments/{code}")
    def delete_dicotopo_department(code: str) -> schemas.SourcesOut:
        runtime = _runtime()
        with state.lock:
            try:
                remove_department(
                    runtime.cache, runtime.index, code, queue=runtime.queue
                )
            except SourceError as exc:
                raise _error(400, str(exc)) from None
            runtime.queue.clear_results(DICOTOPO, code.strip().upper())
            reattach()
        return get_sources()

    @app.put("/api/sources/dicotopo/api")
    def set_dicotopo_api(body: schemas.ApiToggleIn) -> schemas.ApiToggleOut:
        runtime = _runtime()
        with state.lock:
            runtime.set_api_enabled(body.enabled)
            reattach()
        return schemas.ApiToggleOut(api_enabled=runtime.config.dicotopo_api)

    @app.put("/api/sources/geonames/username")
    def set_geonames_username(
        body: schemas.GeoNamesUsernameIn,
    ) -> schemas.GeoNamesUsernameOut:
        """Write-only: the value goes to ``config.json`` and is never sent back,
        logged or quoted in a message; ``null`` (or blank) clears it."""
        runtime = _runtime()
        value = (body.username or "").strip()
        if value and not _GEONAMES_USERNAME.fullmatch(value):
            raise _error(400, _USERNAME_INVALID)
        with state.lock:
            runtime.set_geonames_username(value or None)
            reattach()  # the API may now answer (or no longer)
        return schemas.GeoNamesUsernameOut(
            username_set=bool(runtime.config.geonames_username)
        )

    @app.get("/api/sources/geonames/size/{iso}")
    def geonames_size(iso: str) -> schemas.GeoNamesSizeOut:
        """Size of ``<CC>.zip`` before a download: the cached file, else one
        ``HEAD`` request (short timeout, no user name, outside the lock);
        ``size`` is ``None`` when the server does not answer."""
        runtime = _runtime()
        code = iso.strip().upper()
        try:
            known = len(code) == 2 and code.isascii() and code.isalpha()
            size = runtime.geonames_size(code) if known else None
            if size is None:
                size = country_size(code, opener=runtime.opener)
        except SourceError as exc:
            raise _error(400, str(exc)) from None
        return schemas.GeoNamesSizeOut(iso=code, size=size)

    @app.delete("/api/sources/geonames/countries/{iso}")
    def delete_geonames_country(iso: str) -> schemas.SourcesOut:
        runtime = _runtime()
        with state.lock:
            try:
                remove_country(
                    runtime.cache, runtime.geonames_index, iso, queue=runtime.queue
                )
            except SourceError as exc:
                raise _error(400, str(exc)) from None
            runtime.queue.clear_results(GEONAMES, iso.strip().upper(), field="country")
            reattach()
        return get_sources()

    @app.post("/api/sources/queue/retry")
    def retry_sources_queue() -> schemas.QueueStatus:
        runtime = _runtime()
        runtime.queue.retry_failed()
        return _queue_status(runtime)

    @app.post("/api/sources/cache/clear")
    def clear_sources_cache(body: schemas.CacheClearIn) -> schemas.CacheClearOut:
        runtime = _runtime()
        if body.source not in runtime.sources:
            raise _error(400, f"Source inconnue : {body.source!r}.")
        with state.lock:
            runtime.queue.clear(body.source)
            reattach()
        return schemas.CacheClearOut(cleared=body.source)

    @app.post("/api/places/{place_id}/source-proposals/accept")
    def accept_source_proposal(
        place_id: str, body: schemas.SourceProposalAcceptIn
    ) -> schemas.PlaceOut:
        """Add a level proposed by a source to a place (validated)."""
        model = body.level
        level = Level(
            rank=model.rank,
            name=model.name.strip(),
            written=_blank_to_none(model.written),
            type=_blank_to_none(model.type),
            identifier=_blank_to_none(model.identifier),
            source=_blank_to_none(model.source),
            start=_blank_to_none(model.start),
            end=_blank_to_none(model.end),
            latitude=model.latitude,
            longitude=model.longitude,
            nature=model.nature,
            origin=model.origin,
            status="validated",
        )
        if not level.name:
            raise _error(400, "Le niveau proposé n'a pas de nom.")
        known_sources = set(sources.sources) if sources is not None else {DICOTOPO}
        if level.origin not in known_sources or level.identifier is None:
            raise _error(
                400,
                "Ce niveau ne vient pas d'une source "
                "(origine ou identifiant manquant).",
            )
        with state.lock:
            try:
                entry = registry.add_level(place_id, level, project.project_id)
            except KeyError:
                raise _error(404, "Ce lieu n'existe pas dans le référentiel.") from None
            except ValueError as exc:
                raise _error(400, str(exc)) from None
            _push_correct(entry)
            return _place_out(registry.place(place_id))

    @app.post("/api/source-proposals/refuse")
    def refuse_source_proposal(
        body: schemas.SourceProposalRefuseIn,
    ) -> schemas.SourceProposalRefuseOut:
        """Remember that the user refused a source's proposal for a subject."""
        prefix, _, rest = body.subject.partition(":")
        if prefix not in ("place", "writing") or not rest:
            raise _error(
                400,
                "Sujet invalide : « place:<identifiant> » ou « writing:<écriture> » "
                "attendu.",
            )
        if not body.source.strip() or not body.identifier.strip():
            raise _error(400, "La source et l'identifiant sont obligatoires.")
        with state.lock:
            entry = registry.refuse_source_proposal(
                body.subject, body.source, body.identifier, project.project_id
            )
            _push_correct(entry)
            return schemas.SourceProposalRefuseOut(entry_id=entry)

    # -- countries (GeoNames mode) -------------------------------------------

    def _download(iso: str | None) -> Literal["queued", "running", "failed"] | None:
        """Queue state of the GeoNames download of ``iso`` (not indexed only)."""
        runtime = sources
        if runtime is None or iso is None:
            return None
        if iso in runtime.geonames_index.countries():
            return None
        return download_state(runtime.queue, iso)

    def _country_rows() -> list[schemas.CountryRowOut]:
        return [
            schemas.CountryRowOut(
                iso=row.iso,
                name=row.name,
                writings=row.writings,
                occurrences=row.occurrences,
                mode=row.mode,
                downloaded=row.downloaded,
                download=_download(row.iso),
                overrides=row.overrides,
            )
            for row in project.countries()
        ]

    def _mode_in(value: str | None) -> SourceMode | None:
        if value is None:
            return None
        for mode in _SOURCE_MODES:
            if value == mode:
                return mode
        raise _error(400, _MODE_INVALID)

    @app.get("/api/countries")
    def list_countries() -> schemas.CountriesOut:
        with state.lock:
            return schemas.CountriesOut(countries=_country_rows())

    @app.put("/api/countries/{iso}")
    def set_country_mode(iso: str, body: schemas.ModeIn) -> schemas.CountryModeOut:
        """Choose the GeoNames mode of a country (undoable).

        ``geonames`` for a country not indexed yet queues its download, even when
        the mode is already ``geonames`` (a removed file, a failed download: its
        failed or waiting jobs run again now); the response then gives the
        announced size of the file (one ``HEAD`` request, made outside the lock,
        and not made again while that download is already queued or running).
        """
        mode = _mode_in(body.mode)
        if mode is None:
            raise _error(400, _MODE_INVALID)
        code = iso.strip().upper()
        unknown = f"Code pays inconnu : « {code} » (code ISO à deux lettres attendu)."
        runtime = sources
        queued = False
        known_size = False  # the size was given when this download was asked
        with state.lock:
            if code not in {row.iso for row in project.countries() if row.iso}:
                raise _error(400, unknown)  # also what set_country_mode checks
            if (
                runtime is not None
                and mode == "geonames"
                and code not in runtime.geonames_index.countries()
            ):
                known_size = download_state(runtime.queue, code) in (
                    "queued",
                    "running",
                )
                try:  # request_country checks the code before queueing anything
                    request_country(runtime.queue, code, cache=runtime.cache)
                except SourceError as exc:
                    raise _error(400, str(exc)) from None
                retry_country(runtime.queue, code)
                queued = True
            entry = project.set_country_mode(code, mode)
            _push_correct(entry)
            rows = _country_rows()
        size: int | None = None
        if runtime is not None and mode == "geonames":
            size = runtime.geonames_size(code)
            if size is None and queued and not known_size:
                size = country_size(code, opener=runtime.opener)
        return schemas.CountryModeOut(
            iso=code, mode=mode, queued=queued, size=size, countries=rows
        )

    @app.put("/api/clusters/{cluster_id:path}/geonames")
    def set_cluster_geonames(
        cluster_id: str, body: schemas.ModeIn
    ) -> schemas.ClusterDetail:
        """Correct the GeoNames mode of one place (all its writings; undoable);
        ``null`` goes back to the country setting."""
        mode = _mode_in(body.mode)
        with state.lock:
            _cluster_or_404(project, cluster_id)
            try:
                entry = project.set_cluster_mode(cluster_id, mode)
            except KeyError:
                raise _error(
                    404, "Ce lieu n'existe pas (ou plus) dans la file."
                ) from None
            except ValueError as exc:
                raise _error(400, f"Correction impossible : {exc}.") from None
            _push_correct(entry)
            project.touch(cluster_id)
            return _detail(state, _cluster_or_404(project, cluster_id))

    # -- occurrences --------------------------------------------------------

    @app.post("/api/occurrences")
    def occurrences(body: schemas.OccurrencesIn) -> list[schemas.OccurrenceOut]:
        with state.lock:
            writing = project.writings.get(body.writing)
            if writing is None:
                raise _error(404, "Cette écriture n'est pas dans la base.")
            labels = _labels(state)
            return [_occurrence(labels, o) for o in writing.occurrences]

    # -- precisions ---------------------------------------------------------

    @app.get("/api/precisions")
    def list_precisions(
        statuses: list[PrecisionStatus] | None = Query(None, alias="status"),
    ) -> schemas.PrecisionsOut:
        """Precision groups; every status when no ``status`` is given."""
        wanted = set(statuses) if statuses else set(get_args(PrecisionStatus))
        with state.lock:
            groups = project.precision_groups(wanted)
        return schemas.PrecisionsOut(groups=[_precision_group(g) for g in groups])

    @app.post("/api/precisions/decide")
    def decide_precision(body: schemas.PrecisionDecideIn) -> schemas.PrecisionDecideOut:
        with state.lock:
            group = project.undecided_precision_group(
                body.writing, body.complement, body.period
            )
            if group is None:
                raise _error(400, "Aucune occurrence ne correspond à cette précision.")
            chosen = body.arrondissement_id or None
            quartier = body.quartier_id or None
            if chosen is None:
                if quartier is not None:
                    raise _error(
                        400, "Un quartier suppose un arrondissement : choisissez-en un."
                    )
            else:
                matching = [
                    c for c in group.candidates if c.arrondissement_id == chosen
                ]
                if not matching:
                    raise _error(
                        400,
                        "Cet arrondissement ne fait pas partie des propositions "
                        "de cette précision.",
                    )
                if quartier is not None and all(
                    c.quartier_id != quartier for c in matching
                ):
                    raise _error(
                        400,
                        "Ce quartier ne correspond pas à l'arrondissement choisi.",
                    )
            entry = registry.decide_precision(
                body.writing,
                body.complement,
                body.period,
                chosen,
                quartier,
                project.project_id,
            )
            _push_correct(entry, "precision")
            return schemas.PrecisionDecideOut(entry_id=entry)

    @app.post("/api/precisions/clear")
    def clear_precision(body: schemas.PrecisionClearIn) -> schemas.PrecisionDecideOut:
        """Forget a decision: the group goes back to its computed status."""
        with state.lock:
            entry = registry.clear_precision(
                body.writing, body.complement, body.period, project.project_id
            )
            if entry is None:
                raise _error(400, "Aucune décision à retirer pour cette précision.")
            _push_correct(entry, "precision")
            return schemas.PrecisionDecideOut(entry_id=entry)

    # -- undo ---------------------------------------------------------------

    @app.post("/api/undo")
    def undo() -> schemas.UndoOut:
        with state.lock:
            if not state.undo:
                raise _error(409, "Rien à annuler.")
            action = state.undo.pop()
            try:
                _undo_refs(state, action.refs)
            except _UndoFailed as failed:
                if len(failed.remaining) < len(action.refs):
                    state.undo.append(_Action(action.kind, failed.remaining))
                    raise _error(
                        409,
                        "Action annulée seulement partiellement : une étape n'a pas "
                        f"pu être défaite ({failed.cause}). Le reste de l'action "
                        "reste dans la pile d'annulation ; réessayez.",
                    ) from None
                raise _error(
                    409,
                    "Annulation impossible : une action plus récente a modifié les "
                    f"mêmes décisions ({failed.cause}). Cette action est retirée de "
                    "la pile d'annulation.",
                ) from None
            return schemas.UndoOut(action=action.kind)

    # -- export -------------------------------------------------------------

    @app.get("/api/export")
    def export() -> Response:
        with state.lock:
            data = build_archive(
                project,
                registry,
                ref,
                datetime.now(UTC),
                sources.index.departments() if sources is not None else None,
                sources.geonames_index.countries() if sources is not None else None,
            )
        name = f"{base_stem(project.gw_path.name)}_atelier.zip"
        return Response(
            data,
            media_type="application/zip",
            headers={"Content-Disposition": _attachment(name)},
        )

    # -- registry -----------------------------------------------------------

    @app.get("/api/registry/export")
    def export_registry_file() -> Response:
        with state.lock:
            document = export_registry(registry)
        return Response(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            media_type="application/json",
            headers={"Content-Disposition": _attachment("referentiel_lieux.json")},
        )

    @app.post(_IMPORT_PATH)
    def import_registry_file(file: UploadFile = File(...)) -> schemas.ImportOut:
        data = file.file.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise _error(413, "Fichier trop volumineux (50 Mo au plus).")
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            # RecursionError: nesting deeper than the JSON decoder can follow.
            raise _error(
                400, "Fichier illisible : ce n'est pas un JSON valide (UTF-8)."
            ) from None
        with state.lock:
            try:
                result = import_registry(registry, document, state.ref)
            except RegistryFormatError as exc:
                raise _error(400, f"{IMPORT_FORMAT_ERROR} ({exc})") from None
            added = 0
            if result.entry_id is not None:
                entry = result.entry_id
                state.undo.append(_Action("import", (_Ref("registry", entry),)))
                added = _journal_writing_count(registry, entry)
            for conflict in result.conflicts:
                state.conflicts[conflict.writing] = conflict
            return schemas.ImportOut(added=added, conflicts=_conflicts(state).conflicts)

    @app.get("/api/registry/journal")
    def registry_journal(limit: int = Query(50, ge=1, le=500)) -> schemas.JournalOut:
        with state.lock:
            entries = registry.journal(limit=limit)
            return schemas.JournalOut(
                entries=[_journal_entry(registry, e) for e in entries]
            )

    @app.get("/api/registry/conflicts")
    def pending_conflicts() -> schemas.ConflictsOut:
        with state.lock:
            return _conflicts(state)

    @app.post("/api/registry/conflicts/resolve")
    def resolve(body: schemas.ResolveIn) -> schemas.ConflictsOut:
        with state.lock:
            conflict = state.conflicts.get(body.writing)
            if conflict is None:
                raise _error(404, "Aucun conflit en attente pour cette écriture.")
            try:
                entry = resolve_conflict(
                    registry, conflict, body.keep, project.project_id
                )
            except (StaleConflictError, KeyError):
                del state.conflicts[body.writing]
                raise _error(
                    409,
                    "La décision sur cette écriture a changé depuis l'import : "
                    "importez de nouveau le fichier pour voir le conflit à jour.",
                ) from None
            del state.conflicts[body.writing]
            if entry is not None:
                state.undo.append(_Action("resolve", (_Ref("registry", entry),)))
            return _conflicts(state)

    return app
