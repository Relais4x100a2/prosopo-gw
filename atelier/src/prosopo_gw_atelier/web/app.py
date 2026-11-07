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
    then validate, journal lookups for the undo stack): every endpoint that
    touches them holds ``AppState.lock``, so actions are serialized.

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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar
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
from ..places.model import ElementKind, Occurrence
from ..project import ClusterState, ClusterView, Project
from ..refdata import RefData
from ..store.exchange import (
    Conflict,
    RegistryFormatError,
    StaleConflictError,
    export_registry,
    import_registry,
    resolve_conflict,
)
from ..store.registry import JournalEntry, Origin, Place, PlaceRegistry
from . import schemas

T = TypeVar("T")

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


# -- helpers -------------------------------------------------------------------


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def _latest_entry(registry: PlaceRegistry) -> int:
    latest = registry.journal(limit=1)
    return latest[0].entry_id if latest else 0


def _journaled(
    registry: PlaceRegistry, action: Callable[[], T]
) -> tuple[T, int | None]:
    """Run ``action``; return its result and the journal entry it wrote, if any."""
    before = _latest_entry(registry)
    result = action()
    after = _latest_entry(registry)
    return result, (after if after != before else None)


def _label(view: ClusterView) -> str:
    if view.provisional_name:
        return view.provisional_name
    proposal = view.cluster.proposal
    name = proposal.get("commune") or proposal.get("former_name")
    if name:
        return name
    return view.cluster.writings[0] if view.cluster.writings else view.cluster.id


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
    origins = dict(view.origins or {})
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
        proposal=dict(view.cluster.proposal),
        origins=origins,
        complements=[
            schemas.Complement(text=text, occurrences=count)
            for text, count in sorted(complements.items(), key=lambda i: (-i[1], i[0]))
        ],
        writings=rows,
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
    return place.fields.get("commune") or place.fields.get("former_name")


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
        else:
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
            _, entry = _journaled(
                registry, lambda: registry.detach(decided, project.project_id)
            )
        except BaseException:
            _undo_refs(state, refs)
            raise
        if entry is not None:
            refs.append(_Ref("registry", entry))
    return refs, new.cluster.id


# -- app -----------------------------------------------------------------------


def create_app(project: Project, registry: PlaceRegistry, ref: RefData) -> FastAPI:
    """The atelier's web app over ``project`` and ``registry``."""
    state = AppState(project, registry, ref)
    app = FastAPI(
        title="Atelier prosopo-gw",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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
            fields: dict[ElementKind, str | None] = {
                k: v.strip() or None for k, v in body.fields.items()
            }
            if not any(fields.values()):
                raise _error(
                    400, "La forme retenue est vide : renseignez au moins un champ."
                )
            place_id = view.place_id
            kept = dict(view.origins or {})
            proposal = view.cluster.proposal
            origins: dict[ElementKind, Origin] = {
                kind: kept.get(kind, "rule")
                if proposal.get(kind) == value
                else "manual"
                for kind, value in fields.items()
                if value is not None
            }
            refs: list[_Ref] = []
            split_id: str | None = None
            unchecked = [w for w in members if w not in checked]
            if unchecked:
                refs, split_id = _split_out(state, view, unchecked)
            try:
                new_place, entry = _journaled(
                    registry,
                    lambda: registry.validate(
                        checked, fields, origins, project.project_id, place_id
                    ),
                )
            except BaseException as exc:
                _undo_refs(state, refs)
                if isinstance(exc, KeyError):
                    raise _error(
                        409, "Ce lieu a été supprimé entre-temps ; rechargez la file."
                    ) from None
                raise
            if entry is not None:
                refs.append(_Ref("registry", entry))
            if refs:
                state.undo.append(_Action("validate", tuple(refs)))
            split = None
            if split_id is not None:
                split = _summary(project.cluster(split_id))
            return schemas.ValidateOut(place_id=new_place, split=split)

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
            _, entry = _journaled(
                registry, lambda: registry.reject(writings, project.project_id)
            )
            if entry is not None:
                state.undo.append(_Action("reject", (_Ref("registry", entry),)))
            return schemas.RejectOut(writings=writings)

    # -- places -------------------------------------------------------------

    @app.patch("/api/places/{place_id}")
    def correct_place(place_id: str, body: schemas.CorrectIn) -> schemas.PlaceOut:
        value = body.value.strip() or None
        with state.lock:
            try:
                _, entry = _journaled(
                    registry,
                    lambda: registry.correct(
                        place_id, body.field, value, project.project_id
                    ),
                )
            except KeyError:
                raise _error(404, "Ce lieu n'existe pas dans le référentiel.") from None
            if entry is not None:
                state.undo.append(_Action("correct", (_Ref("registry", entry),)))
            place = registry.place(place_id)
            return schemas.PlaceOut(
                place_id=place.place_id, fields=place.fields, origins=place.origins
            )

    # -- occurrences --------------------------------------------------------

    @app.post("/api/occurrences")
    def occurrences(body: schemas.OccurrencesIn) -> list[schemas.OccurrenceOut]:
        with state.lock:
            writing = project.writings.get(body.writing)
            if writing is None:
                raise _error(404, "Cette écriture n'est pas dans la base.")
            labels = _labels(state)
            return [_occurrence(labels, o) for o in writing.occurrences]

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
            data = build_archive(project, registry, ref, datetime.now(UTC))
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
        except (UnicodeDecodeError, ValueError):
            raise _error(
                400, "Fichier illisible : ce n'est pas un JSON valide (UTF-8)."
            ) from None
        with state.lock:
            try:
                found, entry = _journaled(
                    registry, lambda: import_registry(registry, document)
                )
            except RegistryFormatError as exc:
                raise _error(400, f"{IMPORT_FORMAT_ERROR} ({exc})") from None
            added = 0
            if entry is not None:
                state.undo.append(_Action("import", (_Ref("registry", entry),)))
                added = _journal_writing_count(registry, entry)
            for conflict in found:
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
                _, entry = _journaled(
                    registry,
                    lambda: resolve_conflict(
                        registry, conflict, body.keep, project.project_id
                    ),
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
