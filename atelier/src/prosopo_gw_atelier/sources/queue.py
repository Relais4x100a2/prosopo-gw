"""Persistent background job queue for external sources, plus its worker thread.

Every call opens its own SQLite connection (the queue is used from the worker thread
and from request threads); writes are short transactions.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from prosopo_gw_atelier.places.levels import Level
from prosopo_gw_atelier.sources.base import (
    CredentialsRejected,
    LevelQuery,
    PermanentSourceError,
    QuotaReached,
    Source,
    SourceCandidate,
    SourceError,
)

logger = logging.getLogger(__name__)

JobKind = Literal["download", "index", "match"]
JobState = Literal["pending", "running", "done", "failed"]

BACKOFF_SECONDS = (30, 300, 3600)
_STATES: tuple[JobState, ...] = ("pending", "running", "done", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,
  payload TEXT NOT NULL, priority INTEGER NOT NULL,
  state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT, not_before TEXT
);
CREATE TABLE IF NOT EXISTS results (
  source TEXT NOT NULL, query_key TEXT NOT NULL, candidates TEXT NOT NULL,
  PRIMARY KEY (source, query_key)
);
CREATE TABLE IF NOT EXISTS epochs (
  name TEXT PRIMARY KEY, value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS pauses (
  source TEXT PRIMARY KEY, until REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rejections (
  source TEXT PRIMARY KEY
);
INSERT OR IGNORE INTO epochs(name, value) VALUES ('stored', 0), ('reset', 0);
"""


@dataclass(frozen=True)
class Job:
    id: int
    source: str
    kind: JobKind
    key: str
    payload: dict[str, object]
    priority: int
    state: JobState
    attempts: int
    error: str | None
    not_before: str | None


def _job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        source=row["source"],
        kind=cast(JobKind, row["kind"]),
        key=row["key"],
        payload=json.loads(row["payload"]),
        priority=row["priority"],
        state=cast(JobState, row["state"]),
        attempts=row["attempts"],
        error=row["error"],
        not_before=row["not_before"],
    )


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _encode(candidates: list[SourceCandidate]) -> str:
    return json.dumps([asdict(c) for c in candidates], ensure_ascii=False)


def _decode(text: str) -> list[SourceCandidate]:
    out: list[SourceCandidate] = []
    for raw in json.loads(text):
        raw["parents"] = tuple(Level(**p) for p in raw["parents"])
        out.append(SourceCandidate(**raw))
    return out


class SourceQueue:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        db = sqlite3.connect(self._path, timeout=5)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
        finally:
            db.close()

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """One connection per call; the whole block is one IMMEDIATE transaction."""
        db = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        finally:
            db.close()

    def enqueue(
        self,
        source: str,
        kind: JobKind,
        key: str,
        payload: dict[str, object],
        priority: int,
    ) -> int:
        with self._db() as db:
            row = db.execute(
                "SELECT id, priority FROM jobs WHERE source=? AND kind=? AND key=?"
                " AND state IN ('pending','running','failed')",
                (source, kind, key),
            ).fetchone()
            if row is not None:
                if priority > row["priority"]:
                    db.execute(
                        "UPDATE jobs SET priority=? WHERE id=?", (priority, row["id"])
                    )
                return int(row["id"])
            cur = db.execute(
                "INSERT INTO jobs(source, kind, key, payload, priority, state)"
                " VALUES (?,?,?,?,?,'pending')",
                (source, kind, key, json.dumps(payload), priority),
            )
            return int(cur.lastrowid or 0)

    def bump(self, source: str, key: str, priority: int) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET priority=? WHERE source=? AND key=?"
                " AND state IN ('pending','running') AND priority<?",
                (priority, source, key, priority),
            )

    def next_job(self) -> Job | None:
        now = _iso(self._clock())
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE state='pending'"
                " AND (not_before IS NULL OR not_before<=?)"
                " AND NOT (kind='match' AND source IN"
                " (SELECT source FROM pauses WHERE until>?"
                " UNION SELECT source FROM rejections))"
                " ORDER BY priority DESC, id ASC LIMIT 1",
                (now, self._clock()),
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (row["id"],))
            return replace(_job(row), state="running")

    def pause(self, source: str, until: float) -> None:
        """Keep the pending ``match`` jobs of ``source`` back until ``until``.

        Downloads and indexing are not paused; an existing pause is never shortened."""
        with self._db() as db:
            db.execute(
                "INSERT INTO pauses(source, until) VALUES (?,?)"
                " ON CONFLICT(source) DO UPDATE SET until=MAX(until, excluded.until)",
                (source, until),
            )

    def paused_until(self, source: str) -> float | None:
        """End of the pause of ``source``, or ``None`` when it is not paused."""
        with self._reader() as db:
            row = db.execute(
                "SELECT until FROM pauses WHERE source=?", (source,)
            ).fetchone()
        if row is None or float(row["until"]) <= self._clock():
            return None
        return float(row["until"])

    def reject_credentials(self, source: str) -> None:
        """Hold the pending ``match`` jobs of ``source`` until
        ``clear_credentials_rejection`` (the source refused the account)."""
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO rejections(source) VALUES (?)", (source,))

    def credentials_rejected(self, source: str) -> bool:
        with self._reader() as db:
            row = db.execute(
                "SELECT 1 FROM rejections WHERE source=?", (source,)
            ).fetchone()
        return row is not None

    def clear_credentials_rejection(
        self, source: str, *, retry_failed: bool = False
    ) -> None:
        """Lift the hold of ``reject_credentials``; with ``retry_failed``, also
        put the failed ``match`` jobs of ``source`` back to run now."""
        with self._db() as db:
            db.execute("DELETE FROM rejections WHERE source=?", (source,))
            if retry_failed:
                db.execute(
                    "UPDATE jobs SET state='pending', attempts=0, not_before=NULL"
                    " WHERE source=? AND kind='match' AND state='failed'",
                    (source,),
                )

    def requeue(self, job_id: int) -> None:
        """Put a running job back to ``pending``: no attempt counted, no error."""
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET state='pending' WHERE id=? AND state='running'",
                (job_id,),
            )

    def finish(self, job_id: int) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET state='done', error=NULL, not_before=NULL WHERE id=?",
                (job_id,),
            )

    def fail(self, job_id: int, message: str, *, permanent: bool = False) -> None:
        """Back off 30 s, 300 s, 3600 s after failures 1 to 3, then ``failed``.

        A ``permanent`` failure goes straight to ``failed``."""
        with self._db() as db:
            row = db.execute(
                "SELECT attempts FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"]) + 1
            if not permanent and attempts <= len(BACKOFF_SECONDS):
                wait = BACKOFF_SECONDS[attempts - 1]
                db.execute(
                    "UPDATE jobs SET state='pending', attempts=?, error=?,"
                    " not_before=? WHERE id=?",
                    (
                        attempts,
                        message,
                        _iso(self._clock() + timedelta(seconds=wait).total_seconds()),
                        job_id,
                    ),
                )
            else:
                db.execute(
                    "UPDATE jobs SET state='failed', attempts=?, error=?,"
                    " not_before=NULL WHERE id=?",
                    (attempts, message, job_id),
                )

    def cancel(self, source: str, key: str) -> int:
        """Delete the pending and failed jobs of ``key``; running ones are left."""
        with self._db() as db:
            cur = db.execute(
                "DELETE FROM jobs WHERE source=? AND key=?"
                " AND state IN ('pending','failed')",
                (source, key),
            )
            return cur.rowcount

    def open_states(self, source: str, keys: Sequence[str]) -> set[JobState]:
        """States of the unfinished jobs (pending, running, failed) of ``keys``."""
        if not keys:
            return set()
        marks = ",".join("?" * len(keys))
        with self._reader() as db:
            return {
                cast(JobState, r["state"])
                for r in db.execute(
                    "SELECT DISTINCT state FROM jobs WHERE source=?"
                    f" AND key IN ({marks})"
                    " AND state IN ('pending','running','failed')",
                    (source, *keys),
                )
            }

    def retry(self, source: str, keys: Sequence[str]) -> int:
        """Put the failed and waiting jobs of ``keys`` back to run now (attempts
        reset); running ones are left. Returns the number of jobs touched."""
        if not keys:
            return 0
        marks = ",".join("?" * len(keys))
        with self._db() as db:
            cur = db.execute(
                "UPDATE jobs SET state='pending', attempts=0, not_before=NULL"
                f" WHERE source=? AND key IN ({marks})"
                " AND state IN ('pending','failed')",
                (source, *keys),
            )
            return cur.rowcount

    def retry_failed(self, source: str | None = None) -> None:
        sql = "UPDATE jobs SET state='pending', attempts=0, not_before=NULL"
        sql += " WHERE state='failed'"
        args: tuple[str, ...] = ()
        if source is not None:
            sql += " AND source=?"
            args = (source,)
        with self._db() as db:
            db.execute(sql, args)

    def resume(self) -> None:
        with self._db() as db:
            db.execute("UPDATE jobs SET state='pending' WHERE state='running'")

    def counts(self) -> dict[str, dict[JobState, int]]:
        out: dict[str, dict[JobState, int]] = {}
        with self._db() as db:
            for row in db.execute(
                "SELECT source, state, COUNT(*) AS n FROM jobs GROUP BY source, state"
            ):
                per = out.setdefault(row["source"], dict.fromkeys(_STATES, 0))
                per[cast(JobState, row["state"])] = row["n"]
        return out

    def errors(self, limit: int = 20) -> list[Job]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE error IS NOT NULL ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_job(r) for r in rows]

    def store_result(
        self, source: str, query_key: str, candidates: list[SourceCandidate]
    ) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO results(source, query_key, candidates)"
                " VALUES (?,?,?)",
                (source, query_key, _encode(candidates)),
            )
            db.execute("UPDATE epochs SET value = value + 1 WHERE name = 'stored'")

    @contextlib.contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        """A read-only connection (no write lock), closed on exit."""
        db = sqlite3.connect(self._path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def results(
        self, source: str, query_keys: Collection[str]
    ) -> dict[str, list[SourceCandidate]]:
        """Cached results of many keys in one read (absent keys are not cached)."""
        wanted = list(dict.fromkeys(query_keys))
        out: dict[str, list[SourceCandidate]] = {}
        with self._reader() as db:
            for start in range(0, len(wanted), 500):
                chunk = wanted[start : start + 500]
                marks = ",".join("?" * len(chunk))
                for row in db.execute(
                    "SELECT query_key, candidates FROM results"
                    f" WHERE source=? AND query_key IN ({marks})",
                    (source, *chunk),
                ):
                    out[row["query_key"]] = _decode(row["candidates"])
        return out

    def epochs(self) -> tuple[int, int]:
        """``(stored, reset)``: counters bumped when a result is stored, and when
        results are deleted (``clear``, ``clear_results``)."""
        with self._reader() as db:
            values = {r["name"]: r["value"] for r in db.execute("SELECT * FROM epochs")}
        return values["stored"], values["reset"]

    def failed_keys(self, source: str, kind: JobKind = "match") -> set[str]:
        """Keys of the jobs of ``source`` that failed for good."""
        with self._reader() as db:
            return {
                r["key"]
                for r in db.execute(
                    "SELECT key FROM jobs WHERE source=? AND kind=? AND state='failed'",
                    (source, kind),
                )
            }

    def clear_results(
        self, source: str, value: str, *, field: str = "department"
    ) -> int:
        """Delete the cached results of ``source`` whose query has ``value`` as
        its ``field`` (a department for DicoTopo, ``"country"`` for GeoNames);
        returns how many. Always bumps the reset epoch."""
        with self._db() as db:
            doomed = []
            for row in db.execute(
                "SELECT query_key FROM results WHERE source=?", (source,)
            ):
                try:
                    found = json.loads(row["query_key"]).get(field)
                except (ValueError, AttributeError):
                    continue
                if found == value:
                    doomed.append(row["query_key"])
            db.executemany(
                "DELETE FROM results WHERE source=? AND query_key=?",
                [(source, k) for k in doomed],
            )
            db.execute("UPDATE epochs SET value = value + 1 WHERE name = 'reset'")
            return len(doomed)

    def result(self, source: str, query_key: str) -> list[SourceCandidate] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT candidates FROM results WHERE source=? AND query_key=?",
                (source, query_key),
            ).fetchone()
        return None if row is None else _decode(row["candidates"])

    def clear(self, source: str) -> None:
        """Forget the match jobs and results of ``source``; downloads and indexing
        that are pending or running are kept (they are the user's own requests)."""
        with self._db() as db:
            db.execute(
                "DELETE FROM jobs WHERE source=? AND NOT"
                " (kind IN ('download','index') AND state IN ('pending','running'))",
                (source,),
            )
            db.execute("DELETE FROM results WHERE source=?", (source,))
            db.execute("UPDATE epochs SET value = value + 1 WHERE name = 'reset'")


class RateLimiter:
    """Guarantee a minimum interval between two calls to ``wait``."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                remaining = self._interval - (self._clock() - self._last)
                if remaining > 0:
                    self._sleep(remaining)
            self._last = self._clock()


class Worker:
    def __init__(
        self,
        queue: SourceQueue,
        handlers: Mapping[tuple[str, JobKind], Callable[[Job], None]],
    ) -> None:
        self._queue = queue
        self._handlers = handlers
        self.idle_interval = 1.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> bool:
        job = self._queue.next_job()
        if job is None:
            return False
        handler = self._handlers.get((job.source, job.kind))
        try:
            if handler is None:
                raise SourceError(f"Aucun traitement pour {job.source}/{job.kind}.")
            handler(job)
        except QuotaReached as exc:
            self._queue.pause(job.source, exc.retry_at)
            self._queue.requeue(job.id)
        except CredentialsRejected:
            self._queue.reject_credentials(job.source)
            self._queue.requeue(job.id)
        except PermanentSourceError as exc:
            self._queue.fail(job.id, str(exc), permanent=True)
        except SourceError as exc:
            self._queue.fail(job.id, str(exc))
        except Exception as exc:
            self._queue.fail(job.id, f"Erreur inattendue : {type(exc).__name__}")
        else:
            self._queue.finish(job.id)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                busy = self.run_once()
            except Exception:
                logger.exception("Worker iteration failed")
                busy = False
            if not busy:
                self._stop.wait(self.idle_interval)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if not self._thread.is_alive():
                self._thread = None


def match_payload(query: LevelQuery) -> dict[str, object]:
    """Payload of the ``match`` job of ``query`` (read back by ``handle_match``)."""
    return {
        "name": query.name,
        "type": query.type,
        "parents": list(query.parents),
        "country": query.country,
        "department": query.department,
        "insee": query.insee,
        "role": query.role,
    }


def handle_match(job: Job, *, source: Source, queue: SourceQueue) -> None:
    """Run the ``match`` job: search ``source`` and store the candidates
    (an empty list too: "searched, nothing found").

    A source that cannot answer yet (``can_answer`` false, e.g. department not
    indexed) stores nothing; the job ends done.
    """
    raw = job.payload
    query = LevelQuery(
        name=str(raw["name"]),
        type=cast("str | None", raw.get("type")),
        parents=tuple(cast("list[str]", raw.get("parents") or [])),
        country=cast("str | None", raw.get("country")),
        department=cast("str | None", raw.get("department")),
        insee=cast("str | None", raw.get("insee")),
        role="upper" if raw.get("role") == "upper" else "level",
    )
    if not source.can_answer(query):
        return  # nothing is cached: the source will be asked again once it can
    queue.store_result(job.source, job.key, source.search(query))
