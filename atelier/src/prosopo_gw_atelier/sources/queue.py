"""Persistent background job queue for external sources, plus its worker thread.

Every call opens its own SQLite connection (the queue is used from the worker thread
and from request threads); writes are short transactions.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from prosopo_gw_atelier.places.levels import Level
from prosopo_gw_atelier.sources.base import SourceCandidate, SourceError

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
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
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
                " ORDER BY priority DESC, id ASC LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (row["id"],))
            return replace(_job(row), state="running")

    def finish(self, job_id: int) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET state='done', error=NULL, not_before=NULL WHERE id=?",
                (job_id,),
            )

    def fail(self, job_id: int, message: str) -> None:
        """Back off 30 s, 300 s, 3600 s after failures 1 to 3, then ``failed``."""
        with self._db() as db:
            row = db.execute(
                "SELECT attempts FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"]) + 1
            if attempts <= len(BACKOFF_SECONDS):
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

    def result(self, source: str, query_key: str) -> list[SourceCandidate] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT candidates FROM results WHERE source=? AND query_key=?",
                (source, query_key),
            ).fetchone()
        return None if row is None else _decode(row["candidates"])

    def clear(self, source: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM jobs WHERE source=?", (source,))
            db.execute("DELETE FROM results WHERE source=?", (source,))


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

    def wait(self) -> None:
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
        except SourceError as exc:
            self._queue.fail(job.id, str(exc))
        except Exception as exc:
            self._queue.fail(job.id, f"Erreur inattendue : {type(exc).__name__}")
        else:
            self._queue.finish(job.id)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(1.0)

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
            self._thread = None
