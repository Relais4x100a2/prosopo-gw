"""A project: one ``.gw`` file and the state of its processing (design § 6.4).

Identity
    ``project_id`` is the first 16 hex characters of the SHA-256 of the
    absolute, resolved path of the ``.gw``: reopening the same file finds the
    same project, a copy elsewhere is another project. Decisions this project
    writes to the registry carry ``project=project_id``.

State file
    ``projects_dir / f"{project_id}.sqlite"`` (``PRAGMA user_version = 1``),
    apart from the personal registry::

        project(id = 1, path, sha256, opened_at)
        splits(seq, split_id, parent_id, created_at)
        split_writings(split_id, position, writing)

    ``sha256`` is the fingerprint of the file content at the last open or
    reload: ``gw_changed`` compares the current content with it (``False`` on
    the first open), then stores the new one.

Clusters
    ``build_clusters`` groups the writings of the ``.gw`` (anchors: the
    registry's known places). Decompositions are computed at open and
    ``reload``; clusters are cached until a reload, a split, or a change of the
    registry's known places. Decisions are read from the registry at each
    ``clusters()`` / ``cluster()`` call, so a decision taken through the
    registry shows at once. Writings the registry knows but the ``.gw`` does
    not are simply ignored (§ 6.3).

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
    split left with no writing is not shown. A cluster that loses writings
    gets its proposal, confidence and anchor recomputed from those it keeps;
    one left empty disappears, and a split whose parent disappeared is shown
    at top level (``parent_id=None``).

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
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from geneweb_py import GeneWebParser
from geneweb_py.formats.tables import Table, build_base_tables

from .places.cluster import Cluster, Confidence, KnownPlace, build_clusters
from .places.collect import collect_writings
from .places.decompose import decompose
from .places.model import Decomposition, Writing
from .refdata import RefData
from .store.registry import PlaceRegistry, SchemaVersionError

ClusterState = Literal["todo", "validated", "rejected", "already_decided"]

SCHEMA_VERSION = 1

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

_STATE_RANK: dict[ClusterState, int] = {
    "todo": 0,
    "already_decided": 1,
    "validated": 2,
    "rejected": 3,
}
_CONFIDENCE_RANK: dict[Confidence, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass
class ClusterView:
    """A cluster as the validation queue shows it."""

    cluster: Cluster
    state: ClusterState
    occurrences: int
    parent_id: str | None
    provisional_name: str | None


@dataclass(frozen=True)
class _Split:
    split_id: str
    parent_id: str
    writings: tuple[str, ...]


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
    ) -> None:
        self.gw_path = gw_path.resolve()
        self.project_id = project_id_of(self.gw_path)
        self.state_path = projects_dir / f"{self.project_id}.sqlite"
        self._registry = registry
        self._ref = ref
        self._lock = threading.RLock()
        self._decompositions: dict[str, Decomposition] = {}
        self._splits: list[_Split] = []
        self._cache: tuple[tuple[KnownPlace, ...], list[_Built]] | None = None
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
    ) -> Project:
        """Open (or create) the project of ``gw_path`` and load the file."""
        project = cls(gw_path, registry, ref, projects_dir)
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
            split = _Split(f"split:{uuid.uuid4().hex}", cluster_id, unique)
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
            self._splits.append(split)
            self._cache = None
            return self.cluster(split.split_id)

    # -- internals ------------------------------------------------------------

    def _views(self) -> list[ClusterView]:
        built = self._built()
        decisions = self._registry.decisions(self._decompositions)
        views = []
        for item in built:
            cluster = item.cluster
            found = [decisions.get(w) for w in cluster.writings]
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
                    cluster=cluster,
                    state=state,
                    occurrences=sum(
                        len(self.writings[w].occurrences) for w in cluster.writings
                    ),
                    parent_id=item.parent_id,
                    provisional_name=item.provisional_name,
                )
            )
        return views

    def _built(self) -> list[_Built]:
        known = tuple(self._registry.known_places())
        if self._cache is not None and self._cache[0] == known:
            return self._cache[1]
        built = self._build({place.place_id: place for place in known})
        self._cache = (known, built)
        return built

    def _build(self, known: dict[str, KnownPlace]) -> list[_Built]:
        clusters: dict[str, Cluster] = {
            c.id: c for c in build_clusters(self._decompositions, self._ref, known)
        }
        holder = {w: c.id for c in clusters.values() for w in c.writings}
        parents: dict[str, str | None] = dict.fromkeys(clusters)
        names: dict[str, str | None] = dict.fromkeys(clusters)
        for split in self._splits:
            present = [w for w in split.writings if w in self._decompositions]
            if not present:
                continue
            touched = {holder[w] for w in present}
            for cluster_id in sorted(touched):
                kept = [w for w in clusters[cluster_id].writings if w not in present]
                if kept:
                    clusters[cluster_id] = self._summary(cluster_id, kept, known)
                else:
                    del clusters[cluster_id]
            clusters[split.split_id] = self._summary(split.split_id, present, known)
            parents[split.split_id] = split.parent_id
            names[split.split_id] = present[0]
            for writing in present:
                holder[writing] = split.split_id
        return [
            _Built(
                cluster,
                parents[cluster_id] if parents[cluster_id] in clusters else None,
                names[cluster_id],
            )
            for cluster_id, cluster in clusters.items()
        ]

    def _summary(
        self, cluster_id: str, writings: Sequence[str], known: dict[str, KnownPlace]
    ) -> Cluster:
        """A cluster ``cluster_id`` made of exactly ``writings``.

        Proposal and anchor come from the largest group ``build_clusters``
        finds among them (ties to the smallest id); the confidence is the
        lowest of the groups, since they may not agree.
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

    @staticmethod
    def _read_splits(conn: sqlite3.Connection) -> list[_Split]:
        rows = conn.execute(
            "SELECT s.split_id, s.parent_id, w.writing FROM splits s "
            "JOIN split_writings w ON w.split_id = s.split_id "
            "ORDER BY s.seq, w.position"
        ).fetchall()
        splits: dict[str, _Split] = {}
        for split_id, parent_id, writing in rows:
            previous = splits.get(split_id)
            before = previous.writings if previous else ()
            splits[split_id] = _Split(split_id, parent_id, (*before, writing))
        return list(splits.values())


def _sort_key(view: ClusterView) -> tuple[int, int, int, str]:
    return (
        _STATE_RANK[view.state],
        _CONFIDENCE_RANK[view.cluster.confidence],
        -view.occurrences,
        view.cluster.id,
    )
