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
from collections.abc import Collection, Iterator, Sequence
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
from .places.levels import Level, validated
from .places.model import Decomposition, Occurrence, Writing
from .places.precision import Candidate, Precision, PrecisionStatus, precise
from .refdata import RefData
from .refdata.arrondissements import level_name
from .refdata.paris_table import ParisTable, load_paris_table
from .store.registry import (
    Decision,
    PlaceRegistry,
    PrecisionDecision,
    SchemaVersionError,
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
    """``True`` when ``cluster.levels`` and ``cluster.postal_code`` are the
    place's as the registry has it (proposed levels included), ``False`` when
    they come from the rules."""
    historical_writings: dict[str, str] = field(default_factory=dict)
    """Writing -> the other commune (former or current) it names, when the
    place mixes communes (see the module docstring)."""

    @property
    def needs_manual_levels(self) -> bool:
        """Not rejected and no validated level: the chain is to enter by hand."""
        if self.state == "rejected":
            return False
        return not any(level.status == "validated" for level in self.cluster.levels)


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
class _Built:
    cluster: Cluster
    parent_id: str | None
    provisional_name: str | None


def project_id_of(gw_path: Path) -> str:
    """Id of the project of ``gw_path``: fingerprint of its absolute path."""
    absolute = str(gw_path.resolve())
    return hashlib.sha256(absolute.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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
        gathered: dict[tuple[str, str, str], list[OccurrencePrecision]] = {}
        for item in items:
            key = (
                item.writing,
                item.occurrence.complement or "",
                item.precision.period,
            )
            gathered.setdefault(key, []).append(item)
        groups = []
        for (writing, complement, period), members in gathered.items():
            status = min(
                (m.precision.status for m in members), key=_STATUS_RANK.__getitem__
            )
            if status not in statuses:
                continue
            candidates = tuple(
                dict.fromkeys(c for m in members for c in m.precision.candidates)
            )
            groups.append(
                PrecisionGroup(
                    writing, complement, period, status, candidates, len(members)
                )
            )
        return groups

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
                    result = precise(
                        view.cluster.levels, arrondissement, occurrence, table
                    )
                    if result is None:
                        continue
                    decision = stored.get(
                        (writing, occurrence.complement or "", result.period)
                    )
                    if decision is not None:
                        result = Precision(
                            result.period,
                            "applied",
                            (
                                Candidate(
                                    decision.arrondissement_id or "",
                                    decision.quartier_id,
                                    None,
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
                        levels=levels,
                        postal_code=postal_code,
                    ),
                    state=state,
                    occurrences=sum(
                        len(self.writings[w].occurrences) for w in cluster.writings
                    ),
                    parent_id=item.parent_id,
                    provisional_name=item.provisional_name,
                    place_id=place_id,
                    from_registry=place_id is not None,
                    historical_writings=historical,
                )
            )
        return views

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
