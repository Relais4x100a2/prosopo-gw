from __future__ import annotations

from pathlib import Path

import pytest

from prosopo_gw_atelier.places.levels import Level
from prosopo_gw_atelier.sources.base import LevelQuery, SourceCandidate, SourceError
from prosopo_gw_atelier.sources.queue import Job, RateLimiter, SourceQueue, Worker


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def queue(tmp_path: Path, clock: Clock) -> SourceQueue:
    return SourceQueue(tmp_path / "sources.sqlite", clock)


def test_priority_order(queue: SourceQueue) -> None:
    queue.enqueue("s", "match", "a", {}, 1)
    queue.enqueue("s", "match", "b", {}, 5)
    queue.enqueue("s", "match", "c", {}, 5)
    keys = [j.key for j in (queue.next_job(), queue.next_job(), queue.next_job()) if j]
    assert keys == ["b", "c", "a"]
    assert queue.next_job() is None


def test_enqueue_is_idempotent_and_raises_priority(queue: SourceQueue) -> None:
    first = queue.enqueue("s", "match", "a", {"x": 1}, 1)
    assert queue.enqueue("s", "match", "a", {"x": 1}, 7) == first
    assert queue.enqueue("s", "match", "a", {"x": 1}, 3) == first
    job = queue.next_job()
    assert job is not None and job.priority == 7
    assert queue.next_job() is None
    queue.bump("s", "a", 9)
    assert queue.counts()["s"]["running"] == 1


def test_running_jobs_resume_as_pending(queue: SourceQueue) -> None:
    queue.enqueue("s", "index", "a", {}, 1)
    assert queue.next_job() is not None
    assert queue.next_job() is None
    queue.resume()
    assert queue.next_job() is not None


def test_failure_backoff_then_failed(queue: SourceQueue, clock: Clock) -> None:
    queue.enqueue("s", "download", "a", {}, 1)
    for wait in (30, 300, 3600):
        job = queue.next_job()
        assert job is not None
        queue.fail(job.id, "Réseau indisponible")
        assert queue.next_job() is None
        clock.now += wait - 1
        assert queue.next_job() is None
        clock.now += 1
        queue.resume()
    job = queue.next_job()
    assert job is not None
    queue.fail(job.id, "Réseau indisponible")
    clock.now += 10_000
    assert queue.next_job() is None
    assert queue.counts()["s"]["failed"] == 1
    assert queue.errors()[0].error == "Réseau indisponible"


def test_retry_failed(queue: SourceQueue, clock: Clock) -> None:
    queue.enqueue("s", "download", "a", {}, 1)
    queue.enqueue("t", "download", "a", {}, 1)
    for _ in range(4):
        for _ in range(2):
            job = queue.next_job()
            if job:
                queue.fail(job.id, "x")
        clock.now += 10_000
    assert queue.counts()["s"]["failed"] == 1
    queue.retry_failed("s")
    assert queue.counts()["s"]["pending"] == 1
    assert queue.counts()["t"]["failed"] == 1
    queue.retry_failed()
    assert queue.counts()["t"]["pending"] == 1


def test_results_round_trip_and_unknown_is_none(queue: SourceQueue) -> None:
    cand = SourceCandidate(
        source="s",
        identifier="1",
        name="Lieu",
        type="commune",
        parents=(Level(rank=1, name="Dept", type="departement", latitude=1.5),),
        latitude=1.0,
        longitude=2.0,
        link="http://x",
        insee="12345",
    )
    key = LevelQuery(
        name="Lieu", type=None, parents=(), country=None, department=None, insee=None
    ).key()
    assert queue.result("s", key) is None
    queue.store_result("s", key, [cand])
    assert queue.result("s", key) == [cand]
    queue.store_result("s", key, [])
    assert queue.result("s", key) == []


def test_clear_source(queue: SourceQueue) -> None:
    queue.enqueue("s", "match", "a", {}, 1)
    queue.enqueue("t", "match", "a", {}, 1)
    queue.store_result("s", "k", [])
    queue.clear("s")
    assert "s" not in queue.counts()
    assert queue.result("s", "k") is None
    assert queue.counts()["t"]["pending"] == 1


def test_results_of_an_older_format_are_forgotten(tmp_path: Path) -> None:
    path = tmp_path / "sources.sqlite"
    queue = SourceQueue(path)
    queue.store_result("s", "k", [])
    queue.store_result("t", "k", [])
    assert queue.expire_results("s", 1) is True  # first stamp: older format
    assert queue.result("s", "k") is None
    assert queue.result("t", "k") == []
    queue.store_result("s", "k", [])
    reopened = SourceQueue(path)
    assert reopened.expire_results("s", 1) is False  # same format: kept
    assert reopened.result("s", "k") == []
    assert reopened.expire_results("s", 2) is True
    assert reopened.result("s", "k") is None


def test_interrupted_expiry_is_redone(tmp_path: Path) -> None:
    queue = SourceQueue(tmp_path / "sources.sqlite")
    queue.store_result("s", "k", [])

    def broken(db: object, source: str) -> None:
        raise RuntimeError("interrupted")

    queue._clear = broken  # type: ignore[method-assign,assignment]
    with pytest.raises(RuntimeError):
        queue.expire_results("s", 1)
    del queue._clear
    assert queue.result("s", "k") == []  # nothing was stamped either
    assert queue.expire_results("s", 1) is True
    assert queue.result("s", "k") is None


def test_rate_limiter_waits() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(1.0, lambda: now[0], sleep)
    limiter.wait()
    assert slept == []
    now[0] += 0.25
    limiter.wait()
    assert slept == [0.75]
    now[0] += 5
    limiter.wait()
    assert slept == [0.75]


def test_worker_run_once_calls_handler(queue: SourceQueue) -> None:
    seen: list[Job] = []
    worker = Worker(queue, {("s", "match"): seen.append})
    assert worker.run_once() is False
    queue.enqueue("s", "match", "a", {"q": 1}, 1)
    assert worker.run_once() is True
    assert seen[0].payload == {"q": 1}
    assert queue.counts()["s"]["done"] == 1


def test_handler_exception_marks_failure(queue: SourceQueue) -> None:
    def source_error(job: Job) -> None:
        raise SourceError("Serveur injoignable.")

    def other(job: Job) -> None:
        raise KeyError("x")

    worker = Worker(queue, {("s", "match"): source_error, ("s", "index"): other})
    queue.enqueue("s", "match", "a", {}, 5)
    queue.enqueue("s", "index", "b", {}, 1)
    worker.run_once()
    worker.run_once()
    messages = {j.key: j.error for j in queue.errors()}
    assert messages == {
        "a": "Serveur injoignable.",
        "b": "Erreur inattendue : KeyError",
    }


def test_worker_start_stop_smoke(queue: SourceQueue) -> None:
    worker = Worker(queue, {})
    worker.start()
    worker.stop()


def test_concurrent_enqueue_creates_one_job(queue: SourceQueue) -> None:
    import threading

    threads = [
        threading.Thread(target=queue.enqueue, args=("s", "match", "k", {}, 1))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert queue.counts()["s"]["pending"] == 1


def test_concurrent_next_job_claims_each_once(queue: SourceQueue) -> None:
    import threading

    for i in range(10):
        queue.enqueue("s", "match", f"k{i}", {}, 1)
    claimed: list[int] = []
    lock = threading.Lock()

    def claim() -> None:
        while (job := queue.next_job()) is not None:
            with lock:
                claimed.append(job.id)

    threads = [threading.Thread(target=claim) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 10 and len(set(claimed)) == 10


def test_worker_loop_survives_exceptions(queue: SourceQueue) -> None:
    import time

    seen: list[Job] = []
    queue.enqueue("s", "match", "a", {}, 1)
    real = queue.next_job
    calls = [0]

    def flaky() -> Job | None:
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("boom")
        return real()

    queue.next_job = flaky  # type: ignore[method-assign]
    worker = Worker(queue, {("s", "match"): seen.append})
    worker.idle_interval = 0.01
    worker.start()
    deadline = time.time() + 5
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert len(seen) == 1


def test_permanent_failure_goes_straight_to_failed(
    queue: SourceQueue, clock: Clock
) -> None:
    from prosopo_gw_atelier.sources.base import PermanentSourceError

    def gone(job: Job) -> None:
        raise PermanentSourceError("département absent")

    queue.enqueue("s", "download", "a", {}, 1)
    assert Worker(queue, {("s", "download"): gone}).run_once()
    assert queue.counts()["s"]["failed"] == 1
    assert queue.errors()[0].error == "département absent"
    clock.now += 10_000
    assert queue.next_job() is None


def test_transient_failure_still_backs_off(queue: SourceQueue, clock: Clock) -> None:
    def flaky(job: Job) -> None:
        raise SourceError("réseau")

    queue.enqueue("s", "download", "a", {}, 1)
    assert Worker(queue, {("s", "download"): flaky}).run_once()
    assert queue.counts()["s"]["failed"] == 0
    assert queue.counts()["s"]["pending"] == 1


def test_clear_keeps_pending_and_running_downloads_and_indexing(
    queue: SourceQueue,
) -> None:
    queue.enqueue("s", "download", "DT01", {}, 9)
    queue.enqueue("s", "index", "DT02", {}, 0)
    queue.enqueue("s", "match", "a", {}, 1)
    running = queue.next_job()  # the highest priority: the download
    assert running is not None and running.kind == "download"
    queue.enqueue("s", "download", "DT03", {}, 0)
    queue.store_result("s", "k", [])
    queue.clear("s")
    assert queue.result("s", "k") is None
    counts = queue.counts()["s"]
    assert counts["running"] == 1
    assert counts["pending"] == 2  # the index and the second download
    assert queue.failed_keys("s", "match") == set()
    kinds = {queue.next_job().kind, queue.next_job().kind}  # type: ignore[union-attr]
    assert kinds == {"index", "download"}


def test_clear_drops_finished_and_failed_downloads(queue: SourceQueue) -> None:
    queue.enqueue("s", "download", "DT01", {}, 0)
    job = queue.next_job()
    assert job is not None
    queue.finish(job.id)
    assert "s" not in queue.counts() or queue.counts()["s"].get("pending", 0) == 0
    queue.clear("s")
    assert "s" not in queue.counts()


def test_open_states_and_retry_by_key(queue: SourceQueue) -> None:
    assert queue.open_states("s", ["a", "b"]) == set()
    assert queue.retry("s", []) == 0
    a = queue.enqueue("s", "download", "a", {}, 1)
    queue.enqueue("s", "index", "b", {}, 0)
    queue.enqueue("s", "download", "c", {}, 0)
    queue.fail(a, "gone", permanent=True)
    job = queue.next_job()  # "b" before "c": same priority, lower id
    assert job is not None and job.key == "b"
    queue.fail(job.id, "later")  # waits before a new attempt
    assert queue.open_states("s", ["a", "b"]) == {"failed", "pending"}
    assert queue.next_job() is not None  # "c" runs
    assert queue.open_states("s", ["c"]) == {"running"}
    assert queue.open_states("t", ["a"]) == set()
    assert queue.retry("s", ["a", "b", "c"]) == 2  # the running job is left
    assert queue.open_states("s", ["a", "b"]) == {"pending"}
    job = queue.next_job()
    assert job is not None and job.key == "a" and job.attempts == 0


def test_enqueue_revives_a_failed_job_only_when_asked(queue: SourceQueue) -> None:
    first = queue.enqueue("s", "index", "a", {"at": 1}, 0)
    job = queue.next_job()
    assert job is not None
    queue.fail(job.id, "x", permanent=True)
    assert queue.enqueue("s", "index", "a", {"at": 2}, 0) == first
    assert queue.next_job() is None  # still failed
    assert queue.enqueue("s", "index", "a", {"at": 2}, 0, revive=True) == first
    job = queue.next_job()
    assert job is not None and job.payload == {"at": 2} and job.attempts == 0


def test_retry_of_one_kind_leaves_the_others(queue: SourceQueue) -> None:
    for kind in ("download", "index"):
        queue.enqueue("s", kind, "a", {}, 0)  # type: ignore[arg-type]
        job = queue.next_job()
        assert job is not None
        queue.fail(job.id, "x", permanent=True)
    assert queue.retry("s", ["a"], kind="download") == 1
    job = queue.next_job()
    assert job is not None and job.kind == "download"
    assert queue.next_job() is None
