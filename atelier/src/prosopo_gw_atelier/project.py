"""A project: one ``.gw`` file and the state of its processing (design § 6.4).

Identity
    ``project_id`` is the first 16 hex characters of the SHA-256 of the
    absolute, resolved path of the ``.gw``: reopening the same file finds the
    same project, a copy elsewhere is another project. Decisions this project
    writes to the registry carry ``project=project_id``.

State file
    ``projects_dir / f"{project_id}.sqlite"`` (``PRAGMA user_version = 2``),
    apart from the personal registry::

        project(id = 1, path, sha256, opened_at)
        splits(seq, split_id, parent_id, created_at)
        split_writings(split_id, position, writing)
        split_parent_writings(split_id, writing)   -- since version 2

    Version 1 files are migrated on open (their splits have no parent
    snapshot).

    ``sha256`` is the fingerprint of the file content at the last open or
    reload: ``gw_changed`` compares the current content with it (``False`` on
    the first open), then stores the new one.

Clusters
    Decided writings are attached to their place (§ 6.3, "rattachées
    d'office"): the writings validated to one place form the cluster
    ``place:<place_id>`` (levels: the place's chain in the registry, anchor:
    the place, confidence ``high``). The rejected writings are grouped by
    ``build_clusters`` too, on their own and without anchors, so a rejected
    cluster stays one cluster: ``rejected:<build_clusters id>`` (e.g.
    ``rejected:insee:59350``), no levels, confidence ``low``. The undecided
    writings go through ``build_clusters`` (anchors: the registry's known
    places); a resulting cluster anchored on a place that has a ``place:``
    cluster in this ``.gw`` is merged into it (the merged cluster takes the
    lowest confidence of the two), otherwise it keeps its own id.

    Decisions are read from the registry at each ``clusters()`` / ``cluster()``
    call, so a decision taken through the registry shows at once.
    Decompositions are computed at open and ``reload``; the grouping is cached
    until a reload, a split, or a change of the registry's decisions or known
    places. Place chains are read at each call. Writings the registry knows
    but the ``.gw`` does not are simply ignored. Views hand out copies of the
    cached clusters.

Place of a cluster
    ``ClusterView.place_id`` is the place that validating the cluster
    updates. A ``place:`` cluster is its place; any other cluster whose
    writings are all validated to one same place is that place (typically a
    validated split); otherwise the place is the cluster's anchor, if any.
    A cluster that is a place shows it as the registry has it:
    ``cluster.levels`` is the place's whole chain (validated and proposed
    levels), ``cluster.postal_code`` its postal code, and ``from_registry`` is
    ``True``. Validating it must pass that stored chain back, so attaching a
    writing to a known place never changes its chain in silence. A cluster
    without a place keeps the chain ``build_clusters`` computed from the
    rules (``from_registry=False``).

    ``historical_writings`` (places only) flags a place that mixes a commune
    and one of its former communes (a version 1 place holding ``Lille`` and
    ``Lomme``: the migration never moves writings). The place's own former
    commune is its first validated level when that level is a
    ``commune_historique`` (as for its anchor, ``known_places``). The map
    gives, for each writing of the cluster:

    - whose decomposition names a former commune
      (``Decomposition.historical``) other than the place's own (same code
      and name key), the name of that former commune;
    - when the place has its own former commune, whose decomposition names
      none but resolves to a current commune, the name of that commune (the
      ``Lille`` writing of a place that is now ``Lomme``);
    - whose decomposition names an arrondissement (of Paris, Lyon or
      Marseille) while the place has no ``arrondissement`` level: the name of
      that level (``7e arrondissement``); the user splits and validates it
      apart, nothing changes in silence. A flag above wins.

Precisions
    ``precisions()`` gives, for every occurrence that has an arrondissement
    precision (``places.precision.precise``, on the chain of the occurrence's
    cluster; the Paris street table is the ``paris_table`` argument, loaded on
    first use by default), an ``OccurrencePrecision``, sorted by writing,
    complement, period, table and row. A stored decision of the registry
    (key writing, complement, period) wins: the precision becomes ``applied``
    with one ``manual`` candidate. A decision with no arrondissement (both ids
    ``None``) gives that candidate an empty ``arrondissement_id``: like a
    candidate for a number that did not exist at the date, it is never turned
    into a level. ``precision_groups(statuses)`` gathers them by key. Cached
    until a reload, a split, or a change of the cluster inputs, of the stored
    precision decisions (so decide, clear and undo refresh) or of a place chain.

Levels to enter by hand
    ``ClusterView.needs_manual_levels`` is ``True`` when the cluster is not
    rejected and its chain has no validated level: there is no chain to
    accept, the user has to enter one (or accept a proposed level). Typically
    a ``name:`` cluster made only of unknown codes such as ``99999``
    (``cluster.levels == ()``), or a place whose levels are all proposed. A
    rejected cluster never needs it: it carries no levels on purpose.

State of a cluster
    ``todo`` while one of its writings is undecided (so a new writing that
    joins an anchored cluster sends it back to the queue); once all are
    decided: ``rejected`` if all are rejected, else ``validated`` if every
    decision was taken by this project, else ``already_decided``.

Splits
    A split takes some writings out of a cluster into a new one, id
    ``split:<uuid4 hex>``, whose ``parent_id`` is that cluster and whose
    ``provisional_name`` is the first writing taken out. Splits are stored
    with their writings, in creation order, and replayed in that order on top
    of ``build_clusters`` at every computation: each split pulls its writings
    out of whatever cluster holds them now (a split of a split comes after
    its parent). A stored writing absent from the ``.gw`` is left out of the
    view (it is kept in the file, and comes back if the writing reappears); a
    split left with no writing is not shown. A ``build_clusters`` cluster that
    loses writings gets its levels, postal code, alternatives, confidence and
    anchor recomputed from those it keeps (a ``place:`` or ``rejected:``
    cluster only loses the writings); one left empty disappears. A split
    never has an anchor: the user separated its writings on purpose, it does
    not join a known place by itself.

    The writings of the parent are stored with the split. When the stored
    parent id no longer exists (its grouping changed, e.g. it was validated
    and became ``place:<id>``), the parent is the current non-split cluster
    holding the most of those writings (ties to the smallest id); with none,
    the split is shown at top level (``parent_id=None``).

Source proposals
    ``attach_sources(queue, sources)`` connects the background queue of the
    external sources (DicoTopo). The project then enqueues one ``match`` job per
    query of every cluster (``dicotopo.queries_for`` on the cluster's chain, for
    each of its writings; priority: the occurrences of the cluster) whose result
    is not cached, at attach, at ``reload`` and when a view meets a query not yet
    enqueued. ``touch(cluster_id)`` raises the priority of the queries of the
    cluster the user opens. When every query of a source has its (possibly empty)
    result, ``proposals`` is laid over the cluster's chain: ``cluster.levels``
    then holds the proposed levels (``status="proposed"``, ``origin="dicotopo"``)
    and ``cluster.alternatives`` the whole-chain readings, after the cluster's own.
    ``pending_sources`` names the sources still awaited, ``failed_sources`` those
    whose job failed for good (see the Sources screen). A query the source cannot
    answer yet (department not indexed, API off) is not asked and not cached;
    indexing a department deletes its cached results (``handle_index`` with the
    queue) and the next pass asks again. The project follows the queue through
    its epoch counters, keeps the resolved results in memory and reads pending
    keys in one batch. Nothing is written to
    the registry: validating a proposal is ``add_level`` / ``set_levels`` and
    refusing it ``refuse_source_proposal`` (subject ``place:<place_id>`` for a
    place, else ``writing:<text>`` for each writing of the cluster); a refused
    ``(source, identifier)`` is left out of the candidates before the proposals
    are computed. The subjects read for a cluster are the union of
    ``writing:<w>`` for each of its writings and ``place:<place_id>`` when it has
    a place, so a refusal made before validation survives it. Results are cached per
    cluster once complete, until a reload, attach or change of the cluster, its
    chain or its refusals; a cleared queue result is seen after a reload.

GeoNames mode
    GeoNames only proposes for the clusters whose effective mode is ``geonames``
    (``effective_mode``): the correction of the cluster if every one of its
    writings has the same one (``set_cluster_mode`` writes one registry row per
    writing, so it survives validation, reload and a change of the country
    setting), else the setting of its country (``set_country_mode``, kept in the
    registry and shared by the projects); a correction on only some writings is
    ``partial`` and flagged. ``countries()`` lists the foreign countries of the
    project (a historical one has no ISO code, hence no choice). Switching to
    ``written`` hides the proposals (the overlay memo key holds the mode)
    without clearing the cached results. A refused proposed level is put back to
    the written level it replaced (or dropped) for every source.

Order of ``clusters()``
    Top-level clusters by state (``todo``, ``already_decided``, ``validated``,
    ``rejected``), confidence (high first), occurrences (descending), then id;
    each followed by its splits, recursively, in the same order.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from geneweb_py import GeneWebParser
from geneweb_py.formats.tables import Table, build_base_tables

from .places.cluster import (
    Cluster,
    Confidence,
    KnownPlace,
    build_clusters,
    name_key,
)
from .places.collect import collect_writings
from .places.decompose import decompose
from .places.levels import Level, check_chain, renumber, validated
from .places.model import Decomposition, Occurrence, Writing
from .places.precision import Candidate, Precision, PrecisionStatus, precise
from .refdata import RefData
from .refdata.arrondissements import level_name
from .refdata.paris_table import ParisTable, load_paris_table
from .sources.base import LevelQuery, Source, SourceCandidate
from .sources.dicotopo.source import DICOTOPO
from .sources.dicotopo.source import proposals as dicotopo_proposals
from .sources.dicotopo.source import queries_for as dicotopo_queries
from .sources.geonames.index import GeoNamesIndex
from .sources.geonames.source import GEONAMES
from .sources.geonames.source import proposals as geonames_proposals
from .sources.geonames.source import queries_for as geonames_queries
from .sources.queue import SourceQueue, match_payload
from .store.registry import (
    Decision,
    PlaceRegistry,
    PrecisionDecision,
    SchemaVersionError,
    SourceMode,
)

ClusterState = Literal["todo", "validated", "rejected", "already_decided"]

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE project (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    opened_at TEXT NOT NULL
);
CREATE TABLE splits (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    split_id TEXT NOT NULL UNIQUE,
    parent_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE split_writings (
    split_id TEXT NOT NULL REFERENCES splits (split_id),
    position INTEGER NOT NULL,
    writing TEXT NOT NULL,
    PRIMARY KEY (split_id, position)
);
PRAGMA user_version = 1;
"""

# version -> script bringing the file to version + 1.
_MIGRATIONS = {
    1: """
CREATE TABLE split_parent_writings (
    split_id TEXT NOT NULL REFERENCES splits (split_id),
    writing TEXT NOT NULL,
    PRIMARY KEY (split_id, writing)
);
PRAGMA user_version = 2;
""",
}

_QueriesFor = Callable[[Sequence[Level], Decomposition, RefData], list[LevelQuery]]
_Proposals = Callable[
    [Sequence[Level], Sequence[SourceCandidate]],
    tuple[tuple[Level, ...], tuple[tuple[Level, ...], ...]],
]
# source name -> (queries of a chain, proposals from the candidates).
_ADAPTERS: dict[str, tuple[_QueriesFor, _Proposals]] = {
    DICOTOPO: (lambda levels, d, ref: dicotopo_queries(levels, d), dicotopo_proposals),
    GEONAMES: (
        lambda levels, d, ref: _geonames_queries(levels, d, ref),
        geonames_proposals,
    ),
}
_TOUCH_PRIORITY = 10**9
_FRANCE = "FR"
ModeOrigin = Literal["country", "override", "partial"]

_PLACE = "place:"
_REJECTED = "rejected:"
_SPLIT = "split:"

_STATE_RANK: dict[ClusterState, int] = {
    "todo": 0,
    "already_decided": 1,
    "validated": 2,
    "rejected": 3,
}
_CONFIDENCE_RANK: dict[Confidence, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class ClusterView:
    """A cluster as the validation queue shows it.

    ``cluster`` is a copy: changing it does not change the project.
    """

    cluster: Cluster
    state: ClusterState
    occurrences: int
    parent_id: str | None
    provisional_name: str | None
    place_id: str | None = None
    """The place this cluster is (see "Place of a cluster" in the module
    docstring), ``None`` if it is to be created."""
    from_registry: bool = False
    """``True`` when the chain and ``cluster.postal_code`` start from the place's
    as the registry has it (proposed levels included), ``False`` when they come
    from the rules. ``cluster.levels`` may also carry the sources' proposals
    (``base_levels`` is the chain without them)."""
    base_levels: tuple[Level, ...] = ()
    """The chain before the sources' proposals were laid over it."""
    historical_writings: dict[str, str] = field(default_factory=dict)
    """Writing -> the other commune (former or current) it names, when the
    place mixes communes (see the module docstring)."""
    pending_sources: tuple[str, ...] = ()
    """Sources whose result is still awaited for this cluster."""
    failed_sources: tuple[str, ...] = ()
    """Sources whose job failed for good (see the Sources screen); not pending."""
    geonames_mode: SourceMode = "written"
    """Effective GeoNames mode of the cluster (see "GeoNames mode")."""
    geonames_mode_origin: ModeOrigin = "country"
    """Where it comes from: the country setting, a correction of every writing
    of the cluster, or (``partial``) a correction of only some of them, which
    the screen flags; the country setting then applies."""

    @property
    def alternatives(self) -> tuple[tuple[Level, ...], ...]:
        """Whole-chain readings: the cluster's own, then the sources'."""
        return self.cluster.alternatives

    @property
    def needs_manual_levels(self) -> bool:
        """Not rejected and no validated level: the chain is to enter by hand."""
        if self.state == "rejected":
            return False
        return not any(level.status == "validated" for level in self.cluster.levels)


@dataclass(frozen=True)
class CountryRow:
    """A foreign country named by the writings of the project.

    ``iso`` is ``None`` for a historical country (no GeoNames mode possible).
    ``downloaded`` is the extraction date of the country's GeoNames index, if
    indexed; ``overrides`` the writings of the country with a per-place
    correction.
    """

    iso: str | None
    name: str
    writings: int
    occurrences: int
    mode: SourceMode
    downloaded: str | None
    overrides: int


@dataclass
class _CountryCount:
    iso: str | None
    name: str
    writings: int = 0
    occurrences: int = 0
    overrides: int = 0


@dataclass(frozen=True)
class OccurrencePrecision:
    """The arrondissement precision of one occurrence (module docstring)."""

    occurrence: Occurrence
    writing: str
    place_id: str | None
    precision: Precision


@dataclass(frozen=True)
class PrecisionGroup:
    """Occurrences sharing a decision key ``(writing, complement, period)``.

    ``complement`` is ``""`` without complement. ``status`` is the most
    pressing of the occurrences' (conflict, ambiguous, uncertain, applied);
    ``candidates`` are theirs, without repeats, in order of appearance.
    """

    writing: str
    complement: str
    period: str
    status: PrecisionStatus
    candidates: tuple[Candidate, ...]
    occurrences: int


_STATUS_RANK: dict[PrecisionStatus, int] = {
    "conflict": 0,
    "ambiguous": 1,
    "uncertain": 2,
    "applied": 3,
}


@dataclass(frozen=True)
class _Split:
    split_id: str
    parent_id: str
    writings: tuple[str, ...]
    parent_writings: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Overlay:
    levels: tuple[Level, ...]
    alternatives: tuple[tuple[Level, ...], ...]
    pending: tuple[str, ...]
    failed: tuple[str, ...]


@dataclass(frozen=True)
class _Built:
    cluster: Cluster
    parent_id: str | None
    provisional_name: str | None


def project_id_of(gw_path: Path) -> str:
    """Id of the project of ``gw_path``: fingerprint of its absolute path."""
    absolute = str(gw_path.resolve())
    return hashlib.sha256(absolute.encode("utf-8")).hexdigest()[:16]


def _foreign_country(decomposition: Decomposition, ref: RefData) -> str | None:
    """The country a writing names outside France (as written), else ``None``.

    Only a country RefData recognises counts: one with an ISO code, or a
    historical state listed without one (``Prusse``). An unrecognised last
    segment is never taken for a country.
    """
    for element in decomposition.elements:
        if element.kind == "country":
            if ref.country_iso(element.value) == _FRANCE:
                return None
            return element.value
    return None


def _geonames_queries(
    levels: Sequence[Level], decomposition: Decomposition, ref: RefData
) -> list[LevelQuery]:
    token = _foreign_country(decomposition, ref)
    iso = ref.country_iso(token) if token is not None else None
    if iso is None or iso == _FRANCE:
        return []
    return geonames_queries(levels, iso)


def _revert_refused(
    source: str,
    original: Sequence[Level],
    levels: tuple[Level, ...],
    refused: frozenset[tuple[str, str]],
) -> tuple[Level, ...]:
    """``levels`` without the proposals of ``source`` that were refused.

    A refused proposed level goes back to the written level it replaced (found
    in ``original`` by name), or is dropped if it was inserted.
    """

    def bad(level: Level) -> bool:
        return (
            level.status == "proposed"
            and source in (level.source, level.origin)
            and level.identifier is not None
            and (source, level.identifier) in refused
        )

    if not any(bad(level) for level in levels):
        return levels
    kept: list[Level] = []
    for level in levels:
        if not bad(level):
            kept.append(level)
            continue
        keys = {name_key(n) for n in (level.name, level.written) if n}
        taken = {name_key(k.name) for k in kept}
        taken |= {name_key(k.name) for k in levels if not bad(k)}
        back = next(
            (
                o
                for o in original
                if name_key(o.name) in keys and name_key(o.name) not in taken
            ),
            None,
        )
        if back is not None:
            kept.append(back)
    result = renumber(kept)
    try:
        check_chain(result)
    except ValueError:
        return tuple(original)
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _gather(items: Sequence[OccurrencePrecision]) -> list[PrecisionGroup]:
    """Precisions gathered by ``(writing, complement, period)``, in order."""
    gathered: dict[tuple[str, str, str], list[OccurrencePrecision]] = {}
    for item in items:
        key = (item.writing, item.occurrence.complement or "", item.precision.period)
        gathered.setdefault(key, []).append(item)
    groups = []
    for (writing, complement, period), members in gathered.items():
        status = min(
            (m.precision.status for m in members), key=_STATUS_RANK.__getitem__
        )
        candidates = tuple(
            dict.fromkeys(c for m in members for c in m.precision.candidates)
        )
        groups.append(
            PrecisionGroup(
                writing, complement, period, status, candidates, len(members)
            )
        )
    return groups


class Project:
    """One ``.gw`` file and the state of its processing.

    Safe to share between threads: calls are serialized.
    """

    project_id: str
    gw_changed: bool
    tables: list[Table]
    writings: dict[str, Writing]

    def __init__(
        self,
        gw_path: Path,
        registry: PlaceRegistry,
        ref: RefData,
        projects_dir: Path,
        paris_table: ParisTable | None = None,
    ) -> None:
        self.gw_path = gw_path.resolve()
        self.project_id = project_id_of(self.gw_path)
        self.state_path = projects_dir / f"{self.project_id}.sqlite"
        self._registry = registry
        self._ref = ref
        self._lock = threading.RLock()
        self._decompositions: dict[str, Decomposition] = {}
        self._splits: list[_Split] = []
        self._cache: tuple[object, list[_Built]] | None = None
        self._paris_table = paris_table
        self._precisions: tuple[object, list[OccurrencePrecision]] | None = None
        self._raw_precisions: tuple[object, list[PrecisionGroup]] | None = None
        self._queue: SourceQueue | None = None
        self._geonames_index: GeoNamesIndex | None = None
        self._sources: dict[str, Source] = {}
        self._enqueued: set[tuple[str, str]] = set()
        self._overlays: dict[object, _Overlay] = {}
        self._resolved: dict[tuple[str, str], list[SourceCandidate]] = {}
        self._pending: dict[str, set[str]] = {}
        self._epochs: tuple[int, int] | None = None
        self._queries: dict[str, list[tuple[str, LevelQuery]]] = {}
        self.gw_changed = False
        self.tables = []
        self.writings = {}
        projects_dir.mkdir(parents=True, exist_ok=True)
        self._init_state()

    @classmethod
    def open(
        cls,
        gw_path: Path,
        registry: PlaceRegistry,
        ref: RefData,
        projects_dir: Path,
        paris_table: ParisTable | None = None,
    ) -> Project:
        """Open (or create) the project of ``gw_path`` and load the file."""
        project = cls(gw_path, registry, ref, projects_dir, paris_table)
        project.reload()
        return project

    # -- loading --------------------------------------------------------------

    def reload(self) -> None:
        """Parse the ``.gw`` again; decisions and splits are kept."""
        with self._lock:
            sha = hashlib.sha256(self.gw_path.read_bytes()).hexdigest()
            tables = build_base_tables(GeneWebParser().parse_file(str(self.gw_path)))
            writings = collect_writings(tables)
            self._decompositions = {
                text: decompose(text, self._ref) for text in writings
            }
            self.tables = tables
            self.writings = writings
            with self._connect() as conn:
                row = conn.execute("SELECT sha256 FROM project").fetchone()
                self.gw_changed = row is not None and row[0] != sha
                conn.execute(
                    "INSERT INTO project (id, path, sha256, opened_at) "
                    "VALUES (1, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET "
                    "path = excluded.path, sha256 = excluded.sha256, "
                    "opened_at = excluded.opened_at",
                    (str(self.gw_path), sha, _now()),
                )
                self._splits = self._read_splits(conn)
            self._cache = None
            self._precisions = None
            self._raw_precisions = None
            self._reset_sources()
            if self._queue is not None:
                self._views()

    def attach_sources(
        self,
        queue: SourceQueue,
        sources: Mapping[str, Source],
        geonames_index: GeoNamesIndex | None = None,
    ) -> None:
        """Connect the source queue (module docstring) and enqueue the matches.

        ``geonames_index`` (optional) tells which countries are downloaded.
        """
        with self._lock:
            self._queue = queue
            self._sources = dict(sources)
            self._geonames_index = geonames_index
            self._reset_sources()
            self._views()

    def _reset_sources(self) -> None:
        self._overlays = {}
        self._enqueued = set()
        self._resolved = {}
        self._pending = {}
        self._epochs = None

    def _sync_sources(self, queue: SourceQueue) -> None:
        """Follow the queue: forget what a deletion of results invalidated, and
        read (in one batch per source) the pending keys when results arrived."""
        stored, reset = queue.epochs()
        old = self._epochs
        if old is not None and old[1] != reset:
            self._overlays = {}
            self._enqueued = set()
            self._resolved = {}
        if old is None or old != (stored, reset):
            for name, keys in self._pending.items():
                missing = [k for k in keys if (name, k) not in self._resolved]
                for key, found in queue.results(name, missing).items():
                    self._resolved[(name, key)] = found
        self._epochs = (stored, reset)

    def touch(self, cluster_id: str) -> None:
        """The user opens ``cluster_id``: match its queries first."""
        with self._lock:
            queue = self._queue
            if queue is None:
                return
            self._views()
            for source, query in self._queries.get(cluster_id, []):
                key = query.key()
                if (source, key) in self._resolved:
                    continue
                if (source, key) not in self._enqueued:
                    queue.enqueue(
                        source, "match", key, match_payload(query), _TOUCH_PRIORITY
                    )
                    self._enqueued.add((source, key))
                else:
                    queue.bump(source, key, _TOUCH_PRIORITY)

    # -- queries --------------------------------------------------------------

    def clusters(self) -> list[ClusterView]:
        """Every cluster, in queue order (see the module docstring)."""
        with self._lock:
            views = self._views()
        children: dict[str | None, list[ClusterView]] = {}
        for view in views:
            children.setdefault(view.parent_id, []).append(view)
        for siblings in children.values():
            siblings.sort(key=_sort_key)
        ordered: list[ClusterView] = []

        def walk(parent: str | None) -> None:
            for view in children.get(parent, []):
                ordered.append(view)
                walk(view.cluster.id)

        walk(None)
        return ordered

    def cluster(self, cluster_id: str) -> ClusterView:
        """The cluster ``cluster_id``; ``KeyError`` if there is none."""
        with self._lock:
            for view in self._views():
                if view.cluster.id == cluster_id:
                    return view
        raise KeyError(cluster_id)

    # -- GeoNames mode ---------------------------------------------------------

    def countries(self) -> list[CountryRow]:
        """Foreign countries of the project, most writings first (France left out)."""
        with self._lock:
            modes = self._registry.country_modes()
            corrected = self._registry.overrides(GEONAMES)
            dates = self._geonames_dates()
            groups: dict[str, _CountryCount] = {}
            for text, decomposition in self._decompositions.items():
                token = _foreign_country(decomposition, self._ref)
                if token is None:
                    continue
                iso = self._ref.country_iso(token)
                name = self._ref.country(token) or token
                count = groups.setdefault(
                    iso or f"name:{name_key(name)}", _CountryCount(iso, name)
                )
                count.writings += 1
                count.occurrences += len(self.writings[text].occurrences)
                if text in corrected:
                    count.overrides += 1
        rows = [
            CountryRow(
                iso=c.iso,
                name=c.name,
                writings=c.writings,
                occurrences=c.occurrences,
                mode=modes.get(c.iso, "written") if c.iso else "written",
                downloaded=dates.get(c.iso) if c.iso else None,
                overrides=c.overrides,
            )
            for c in groups.values()
        ]
        rows.sort(key=lambda r: (-r.writings, r.name))
        return rows

    def _geonames_dates(self) -> dict[str, str]:
        if self._geonames_index is None:
            return {}
        try:
            return self._geonames_index.countries()
        except sqlite3.Error:
            return {}

    def effective_mode(self, cluster_id: str) -> tuple[SourceMode, ModeOrigin]:
        """GeoNames mode of a cluster and where it comes from (module docstring)."""
        view = self.cluster(cluster_id)
        return view.geonames_mode, view.geonames_mode_origin

    def set_country_mode(self, country: str, mode: SourceMode) -> int | None:
        """Choose the GeoNames mode of a country (ISO alpha-2 code).

        Returns the registry journal entry id (``None`` if nothing changes).
        ``ValueError`` for a name with no ISO code (historical country) or a
        code RefData does not know.
        """
        code = country.strip().upper()
        if not self._ref.is_country_iso(code):
            raise ValueError(f"code pays inconnu : {country!r} (mode non réglable)")
        with self._lock:
            entry = self._registry.set_country_mode(code, mode, self.project_id)
            self._views()
            return entry

    def set_cluster_mode(self, cluster_id: str, mode: SourceMode | None) -> int | None:
        """Correct the GeoNames mode of a cluster (one correction per writing);
        ``None`` removes the correction. Returns the registry journal entry id.

        ``ValueError`` when asking ``geonames`` for a cluster with no country
        that has an ISO code (nothing could be proposed).
        """
        with self._lock:
            writings = self.cluster(cluster_id).cluster.writings
            if mode == "geonames" and not self._isos(writings):
                raise ValueError(
                    "aucun pays reconnu pour ce lieu : GeoNames impossible"
                )
            entry = self._registry.set_override(
                writings, GEONAMES, mode, self.project_id
            )
            self._views()
            return entry

    def _isos(self, writings: Sequence[str]) -> set[str]:
        isos = set()
        for text in writings:
            token = _foreign_country(self._decompositions[text], self._ref)
            iso = self._ref.country_iso(token) if token is not None else None
            if iso is not None:
                isos.add(iso)
        return isos

    def _mode_of(
        self,
        writings: Sequence[str],
        modes: Mapping[str, SourceMode],
        corrected: Mapping[str, SourceMode],
    ) -> tuple[SourceMode, ModeOrigin]:
        isos = self._isos(writings)
        country: SourceMode = (
            "geonames"
            if isos and all(modes.get(i) == "geonames" for i in isos)
            else "written"
        )
        found = [corrected.get(text) for text in writings]
        if found and all(m is not None for m in found) and len(set(found)) == 1:
            mode = found[0]
            if mode is not None:
                return mode, "override"
        if any(m is not None for m in found):
            return country, "partial"
        return country, "country"

    # -- actions --------------------------------------------------------------

    def split(self, cluster_id: str, writings: Sequence[str]) -> ClusterView:
        """Take ``writings`` out of cluster ``cluster_id`` into a new cluster.

        ``writings`` must be a non-empty strict subset of the cluster's
        writings (``ValueError`` otherwise; ``KeyError`` for an unknown
        cluster). Returns the new cluster.
        """
        with self._lock:
            origin = self.cluster(cluster_id)
            unique = tuple(dict.fromkeys(writings))
            members = set(origin.cluster.writings)
            if not unique:
                raise ValueError("split needs at least one writing")
            if not set(unique) <= members:
                unknown = sorted(set(unique) - members)
                raise ValueError(f"writings not in {cluster_id}: {unknown}")
            if len(unique) == len(members):
                raise ValueError("split cannot take every writing of the cluster")
            split = _Split(
                f"{_SPLIT}{uuid.uuid4().hex}",
                cluster_id,
                unique,
                frozenset(origin.cluster.writings),
            )
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO splits (split_id, parent_id, created_at) "
                    "VALUES (?, ?, ?)",
                    (split.split_id, split.parent_id, _now()),
                )
                conn.executemany(
                    "INSERT INTO split_writings (split_id, position, writing) "
                    "VALUES (?, ?, ?)",
                    [(split.split_id, i, w) for i, w in enumerate(unique)],
                )
                conn.executemany(
                    "INSERT INTO split_parent_writings (split_id, writing) "
                    "VALUES (?, ?)",
                    [(split.split_id, w) for w in sorted(split.parent_writings)],
                )
            self._splits.append(split)
            self._cache = None
            self._precisions = None
            self._raw_precisions = None
            return self.cluster(split.split_id)

    def unsplit(self, split_id: str) -> None:
        """Remove the split ``split_id``: its writings go back to the grouping.

        Removed from the state file too (``KeyError`` if there is no such
        split). Splits made of it later keep their writings and find their
        parent as described in the module docstring.
        """
        with self._lock:
            if not any(split.split_id == split_id for split in self._splits):
                raise KeyError(split_id)
            with self._connect() as conn:
                for table in ("split_writings", "split_parent_writings", "splits"):
                    conn.execute(f"DELETE FROM {table} WHERE split_id = ?", (split_id,))
            self._splits = [s for s in self._splits if s.split_id != split_id]
            self._cache = None
            self._precisions = None
            self._raw_precisions = None

    @property
    def paris_table(self) -> ParisTable:
        """The Paris street table (loaded on first use unless injected)."""
        with self._lock:
            if self._paris_table is None:
                self._paris_table = load_paris_table()
            return self._paris_table

    def precisions(self) -> list[OccurrencePrecision]:
        """The precision of every occurrence that has one (module docstring)."""
        with self._lock:
            return list(self._precision_state())

    def precision_groups(
        self, statuses: Collection[PrecisionStatus]
    ) -> list[PrecisionGroup]:
        """Precisions gathered by ``(writing, complement, period)``.

        Only the groups whose status is in ``statuses``; ordered by writing,
        complement, period.
        """
        with self._lock:
            items = self._precision_state()
        return [g for g in _gather(items) if g.status in statuses]

    def undecided_precision_group(
        self, writing: str, complement: str, period: str
    ) -> PrecisionGroup | None:
        """The group as computed WITHOUT any stored decision, or ``None``.

        What the user may choose among, whether or not a decision is already
        stored for the key (a stored one shows only its manual candidate).
        Cached like the clusters; ``None`` if no occurrence has this key.
        """
        with self._lock:
            decisions = self._registry.decisions(self._decompositions)
            self._built(decisions)
            chains = [(p.place_id, p.levels) for p in self._registry.places()]
            assert self._cache is not None
            key = (self._cache[0], chains)
            if self._raw_precisions is None or self._raw_precisions[0] != key:
                self._raw_precisions = (key, _gather(self._compute_precisions({})))
            groups = self._raw_precisions[1]
        for group in groups:
            if (group.writing, group.complement, group.period) == (
                writing,
                complement,
                period,
            ):
                return group
        return None

    def decomposition(self, writing: str) -> Decomposition:
        """Decomposition of ``writing``; ``KeyError`` if it is not in the ``.gw``."""
        with self._lock:
            return self._decompositions[writing]

    # -- internals ------------------------------------------------------------

    def _precision_state(self) -> list[OccurrencePrecision]:
        """Computed precisions, cached with the clusters (module docstring).

        The key adds the stored precision decisions and the place chains to the
        clusters' own, so a decision, its undo or a chain change refreshes.
        """
        decisions = self._registry.decisions(self._decompositions)
        self._built(decisions)
        stored = self._registry.precision_decisions()
        chains = [(p.place_id, p.levels) for p in self._registry.places()]
        assert self._cache is not None
        key = (self._cache[0], tuple(stored.items()), chains)
        if self._precisions is not None and self._precisions[0] == key:
            return self._precisions[1]
        computed = self._compute_precisions(stored)
        self._precisions = (key, computed)
        return computed

    def _compute_precisions(
        self, stored: dict[tuple[str, str, str], PrecisionDecision]
    ) -> list[OccurrencePrecision]:
        table = self.paris_table
        found: list[OccurrencePrecision] = []
        for view in self._views():
            for writing in view.cluster.writings:
                arrondissement = self._decompositions[writing].arrondissement
                for occurrence in self.writings[writing].occurrences:
                    # base levels: the cache key does not cover the sources' overlay
                    result = precise(
                        view.base_levels or view.cluster.levels,
                        arrondissement,
                        occurrence,
                        table,
                    )
                    if result is None:
                        continue
                    decision = stored.get(
                        (writing, occurrence.complement or "", result.period)
                    )
                    if decision is not None:
                        quartier = next(
                            (
                                c.quartier
                                for c in result.candidates
                                if (c.arrondissement_id, c.quartier_id)
                                == (decision.arrondissement_id, decision.quartier_id)
                            ),
                            None,
                        )
                        result = Precision(
                            result.period,
                            "applied",
                            (
                                Candidate(
                                    decision.arrondissement_id or "",
                                    decision.quartier_id,
                                    quartier,
                                    "manual",
                                ),
                            ),
                        )
                    found.append(
                        OccurrencePrecision(occurrence, writing, view.place_id, result)
                    )
        found.sort(
            key=lambda p: (
                p.writing,
                p.occurrence.complement or "",
                p.precision.period,
                p.occurrence.table,
                p.occurrence.row_id,
            )
        )
        return found

    def _views(self) -> list[ClusterView]:
        decisions = self._registry.decisions(self._decompositions)
        built = self._built(decisions)
        places = {place.place_id: place for place in self._registry.places()}
        refusals: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for subject, source, identifier in self._registry.all_refusals():
            refusals[subject].add((source, identifier))
        modes = self._registry.country_modes()
        corrected = self._registry.overrides(GEONAMES)
        overlays: dict[object, _Overlay] = {}
        queries: dict[str, list[tuple[str, LevelQuery]]] = {}
        pending: dict[str, set[str]] = {}
        failed: dict[str, set[str]] = {}
        if self._queue is not None:
            self._sync_sources(self._queue)
            failed = {
                name: self._queue.failed_keys(name)
                for name, keys in self._pending.items()
                if keys
            }
        views = []
        for item in built:
            cluster = item.cluster
            levels, postal_code = cluster.levels, cluster.postal_code
            found = [decisions.get(w) for w in cluster.writings]
            place_id = _decided_place(cluster, found)
            if place_id is None:
                place_id = cluster.anchor_place_id
            historical: dict[str, str] = {}
            if place_id is not None:
                place = places[place_id]
                levels, postal_code = place.levels, place.postal_code
                historical = self._historical_writings(cluster.writings, levels)
            occurrences = sum(
                len(self.writings[w].occurrences) for w in cluster.writings
            )
            subjects = [f"writing:{w}" for w in cluster.writings]
            if place_id is not None:
                subjects.append(f"{_PLACE}{place_id}")
            refused = frozenset().union(*(refusals[s] for s in subjects))
            mode, origin = self._mode_of(cluster.writings, modes, corrected)
            overlay = self._overlay(
                cluster,
                levels,
                occurrences,
                refused,
                overlays,
                queries,
                pending,
                failed,
                mode == "geonames",
            )
            state: ClusterState
            if any(d is None for d in found):
                state = "todo"
            elif all(d is not None and d.status == "rejected" for d in found):
                state = "rejected"
            elif all(d is not None and d.project == self.project_id for d in found):
                state = "validated"
            else:
                state = "already_decided"
            views.append(
                ClusterView(
                    cluster=replace(
                        cluster,
                        writings=list(cluster.writings),
                        levels=overlay.levels,
                        postal_code=postal_code,
                        alternatives=overlay.alternatives,
                    ),
                    state=state,
                    occurrences=occurrences,
                    parent_id=item.parent_id,
                    provisional_name=item.provisional_name,
                    place_id=place_id,
                    from_registry=place_id is not None,
                    historical_writings=historical,
                    pending_sources=overlay.pending,
                    failed_sources=overlay.failed,
                    base_levels=levels,
                    geonames_mode=mode,
                    geonames_mode_origin=origin,
                )
            )
        self._overlays = overlays
        self._queries = queries
        self._pending = pending
        return views

    def _overlay(
        self,
        cluster: Cluster,
        levels: tuple[Level, ...],
        occurrences: int,
        refused: frozenset[tuple[str, str]],
        overlays: dict[object, _Overlay],
        queries: dict[str, list[tuple[str, LevelQuery]]],
        pending_keys: dict[str, set[str]],
        failed_keys: dict[str, set[str]],
        geonames_on: bool = False,
    ) -> _Overlay:
        """The chain and alternatives of a cluster with the sources' proposals."""
        plain = _Overlay(levels, cluster.alternatives, (), ())
        queue = self._queue
        if queue is None or not levels:
            return plain
        key = (cluster.id, levels, tuple(cluster.writings), refused, geonames_on)
        cached = self._overlays.get(key)
        if cached is not None:
            overlays[key] = cached
            return cached
        chain, alternatives = levels, cluster.alternatives
        pending: list[str] = []
        failing: list[str] = []
        asked: list[tuple[str, LevelQuery]] = []
        for name, source_adapter in _ADAPTERS.items():
            if name not in self._sources:
                continue
            if name == GEONAMES and not geonames_on:
                continue
            wanted: dict[str, LevelQuery] = {}
            for writing in cluster.writings:
                for query in source_adapter[0](
                    levels, self._decompositions[writing], self._ref
                ):
                    wanted.setdefault(query.key(), query)
            live = self._sources[name]
            wanted = {k: q for k, q in wanted.items() if live.can_answer(q)}
            known_pending = self._pending.get(name, set())
            unknown = [
                k
                for k in wanted
                if (name, k) not in self._resolved and k not in known_pending
            ]
            if unknown:
                for found_key, found in queue.results(name, unknown).items():
                    self._resolved[(name, found_key)] = found
            candidates: list[SourceCandidate] = []
            waiting: list[str] = []
            for query_key, query in wanted.items():
                asked.append((name, query))
                resolved = self._resolved.get((name, query_key))
                if resolved is None:
                    waiting.append(query_key)
                    pending_keys.setdefault(name, set()).add(query_key)
                    if (name, query_key) not in self._enqueued:
                        queue.enqueue(
                            name, "match", query_key, match_payload(query), occurrences
                        )
                        self._enqueued.add((name, query_key))
                else:
                    candidates += resolved
            if waiting:
                if any(k in failed_keys.get(name, ()) for k in waiting):
                    failing.append(name)
                else:
                    pending.append(name)
                continue
            usable = [c for c in candidates if (name, c.identifier) not in refused]
            proposed, readings = source_adapter[1](chain, usable)
            proposed = _revert_refused(name, chain, proposed, refused)
            readings = tuple(_revert_refused(name, chain, r, refused) for r in readings)
            before = chain
            if proposed:
                chain = proposed
            alternatives = alternatives + tuple(
                r for r in readings if r not in (before, chain)
            )
        queries[cluster.id] = asked
        result = _Overlay(chain, alternatives, tuple(pending), tuple(failing))
        if not pending and not failing:
            overlays[key] = result
        return result

    def _historical_writings(
        self, writings: Sequence[str], levels: Sequence[Level]
    ) -> dict[str, str]:
        """Writings naming another commune than the place's (module docstring)."""
        chain = validated(levels)
        own: str | None = None
        if chain and chain[0].type == "commune_historique":
            own = f"{chain[0].identifier}|{name_key(chain[0].name)}"
        flagged: dict[str, str] = {}
        has_arrondissement = any(level.type == "arrondissement" for level in levels)
        for writing in writings:
            decomposition = self._decompositions[writing]
            former = decomposition.historical
            if former is not None:
                if f"{former.insee}|{name_key(former.name)}" != own:
                    flagged[writing] = former.name
            elif own is not None and decomposition.insee is not None:
                commune = self._ref.commune_by_insee(decomposition.insee)
                if commune is not None:
                    flagged[writing] = commune.name
            written = decomposition.arrondissement
            if written is not None and not has_arrondissement:
                flagged.setdefault(writing, level_name(written.number))
        return flagged

    def _built(self, decisions: dict[str, Decision]) -> list[_Built]:
        known = tuple(self._registry.known_places())
        key = (known, tuple(sorted(decisions.items())))
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        built = self._build({place.place_id: place for place in known}, decisions)
        self._cache = (key, built)
        return built

    def _grouped(
        self, known: dict[str, KnownPlace], decisions: dict[str, Decision]
    ) -> dict[str, Cluster]:
        """Validated writings by place; rejected and undecided writings, each
        apart, by ``build_clusters``."""
        undecided: dict[str, Decomposition] = {}
        by_place: dict[str, list[str]] = defaultdict(list)
        rejected: dict[str, Decomposition] = {}
        for writing, decomposition in self._decompositions.items():
            decision = decisions.get(writing)
            if decision is None:
                undecided[writing] = decomposition
            elif decision.status == "rejected" or decision.place_id is None:
                rejected[writing] = decomposition
            else:
                by_place[decision.place_id].append(writing)
        clusters: dict[str, Cluster] = {}
        for place_id in sorted(by_place):
            cluster_id = f"{_PLACE}{place_id}"
            # The levels are read from the registry by ``_views``.
            clusters[cluster_id] = Cluster(
                cluster_id, sorted(by_place[place_id]), (), None, "high", place_id
            )
        for cluster in build_clusters(rejected, self._ref, {}):
            cluster_id = f"{_REJECTED}{cluster.id}"
            clusters[cluster_id] = Cluster(
                cluster_id, sorted(cluster.writings), (), None, "low"
            )
        for cluster in build_clusters(undecided, self._ref, known):
            target = f"{_PLACE}{cluster.anchor_place_id}"
            if cluster.anchor_place_id is not None and target in clusters:
                place = clusters[target]
                clusters[target] = replace(
                    place,
                    writings=sorted(place.writings + cluster.writings),
                    confidence=_lowest(place.confidence, cluster.confidence),
                )
            else:
                clusters[cluster.id] = cluster
        return clusters

    def _build(
        self, known: dict[str, KnownPlace], decisions: dict[str, Decision]
    ) -> list[_Built]:
        clusters = self._grouped(known, decisions)
        holder = {w: c.id for c in clusters.values() for w in c.writings}
        replayed: list[tuple[_Split, list[str]]] = []
        for split in self._splits:
            present = [w for w in split.writings if w in self._decompositions]
            if not present:
                continue
            touched = {holder[w] for w in present}
            for cluster_id in sorted(touched):
                cluster = clusters[cluster_id]
                kept = [w for w in cluster.writings if w not in present]
                if not kept:
                    del clusters[cluster_id]
                elif cluster_id.startswith((_PLACE, _REJECTED)):
                    clusters[cluster_id] = replace(cluster, writings=kept)
                else:
                    anchors = {} if cluster_id.startswith(_SPLIT) else known
                    clusters[cluster_id] = self._summary(cluster_id, kept, anchors)
            # Never anchored: the user took these writings out on purpose.
            clusters[split.split_id] = self._summary(split.split_id, present, {})
            replayed.append((split, present))
            for writing in present:
                holder[writing] = split.split_id
        parents: dict[str, str | None] = {}
        names: dict[str, str] = {}
        for split, present in replayed:
            if split.split_id in clusters:
                parents[split.split_id] = _parent(split, clusters)
                names[split.split_id] = present[0]
        return [
            _Built(cluster, parents.get(cluster_id), names.get(cluster_id))
            for cluster_id, cluster in clusters.items()
        ]

    def _summary(
        self, cluster_id: str, writings: Sequence[str], known: dict[str, KnownPlace]
    ) -> Cluster:
        """A cluster ``cluster_id`` made of exactly ``writings``.

        Levels, postal code, alternatives and anchor come from the largest
        group ``build_clusters`` finds among them (ties to the smallest id);
        the confidence is the lowest of the groups, since they may not agree.
        """
        groups = build_clusters(
            {w: self._decompositions[w] for w in writings}, self._ref, known
        )
        main = min(groups, key=lambda c: (-len(c.writings), c.id))
        confidence = max(
            (c.confidence for c in groups), key=lambda c: _CONFIDENCE_RANK[c]
        )
        return replace(
            main, id=cluster_id, writings=sorted(writings), confidence=confidence
        )

    # -- state file -------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection to the state file, inside one transaction."""
        with closing(sqlite3.connect(self.state_path)) as conn:
            conn.execute("PRAGMA busy_timeout = 5000")
            with conn:
                yield conn

    def _init_state(self) -> None:
        with closing(sqlite3.connect(self.state_path, isolation_level=None)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"{self.state_path}: project schema version {version} is newer "
                    f"than the supported version {SCHEMA_VERSION}; upgrade the atelier"
                )
            if version == 0:
                conn.executescript(f"BEGIN IMMEDIATE;\n{_SCHEMA}\nCOMMIT;")
                version = 1
            while version < SCHEMA_VERSION:
                script = _MIGRATIONS[version]
                conn.executescript(f"BEGIN IMMEDIATE;\n{script}\nCOMMIT;")
                version += 1

    @staticmethod
    def _read_splits(conn: sqlite3.Connection) -> list[_Split]:
        rows = conn.execute(
            "SELECT s.split_id, s.parent_id, w.writing FROM splits s "
            "JOIN split_writings w ON w.split_id = s.split_id "
            "ORDER BY s.seq, w.position"
        ).fetchall()
        snapshots: dict[str, set[str]] = defaultdict(set)
        for split_id, writing in conn.execute(
            "SELECT split_id, writing FROM split_parent_writings"
        ):
            snapshots[split_id].add(writing)
        writings: dict[str, list[str]] = {}
        parents: dict[str, str] = {}
        for split_id, parent_id, writing in rows:
            writings.setdefault(split_id, []).append(writing)
            parents[split_id] = parent_id
        return [
            _Split(
                split_id,
                parents[split_id],
                tuple(members),
                frozenset(snapshots[split_id]),
            )
            for split_id, members in writings.items()
        ]


def _lowest(*levels: Confidence) -> Confidence:
    return max(levels, key=lambda level: _CONFIDENCE_RANK[level])


def _decided_place(cluster: Cluster, found: Sequence[Decision | None]) -> str | None:
    """The place a cluster is by the registry's decisions, if any.

    A ``place:`` cluster is its place; any other cluster whose writings are
    all validated to one same place is that place.
    """
    if cluster.id.startswith(_PLACE):
        return cluster.id[len(_PLACE) :]
    places = {
        d.place_id if d is not None and d.status == "validated" else None for d in found
    }
    if len(places) == 1:
        (place_id,) = places
        return place_id
    return None


def _parent(split: _Split, clusters: dict[str, Cluster]) -> str | None:
    """Current parent of ``split`` (see the module docstring)."""
    if split.parent_id in clusters:
        return split.parent_id
    best: tuple[int, str] | None = None
    for cluster_id, cluster in clusters.items():
        if cluster_id.startswith(_SPLIT):
            continue
        shared = len(split.parent_writings.intersection(cluster.writings))
        if shared and (best is None or (-shared, cluster_id) < best):
            best = (-shared, cluster_id)
    return best[1] if best is not None else None


def _sort_key(view: ClusterView) -> tuple[int, int, int, str]:
    return (
        _STATE_RANK[view.state],
        _CONFIDENCE_RANK[view.cluster.confidence],
        -view.occurrences,
        view.cluster.id,
    )
