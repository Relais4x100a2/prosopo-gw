from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO

import pytest

from prosopo_gw_atelier.sources.base import SourceError
from prosopo_gw_atelier.sources.dicotopo import download as dl
from prosopo_gw_atelier.sources.dicotopo.index import DicoTopoIndex
from prosopo_gw_atelier.sources.queue import SourceQueue, Worker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "dicotopo"


class FakeServer:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> BinaryIO:
        url = request.full_url
        self.urls.append(url)
        if url == dl.CONTENTS_URL:
            entries = [{"name": f"DT{d}", "type": "dir"} for d in ("62", "59")]
            entries.append({"name": "README.md", "type": "file"})
            return io.BytesIO(json.dumps(entries).encode())  # type: ignore[return-value]
        for dept in ("62", "59"):
            if url == dl.RAW_URL.replace("{dept}", dept):
                return io.BytesIO((FIXTURES / f"DT{dept}.xml").read_bytes())  # type: ignore[return-value]
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]


@pytest.fixture
def queue(tmp_path: Path) -> SourceQueue:
    return SourceQueue(tmp_path / "q.sqlite")


def _worker(
    queue: SourceQueue, cache: Path, index: DicoTopoIndex, server: FakeServer
) -> Worker:
    return Worker(
        queue,
        {
            (dl.DICOTOPO, "download"): lambda job: dl.handle_download(
                job, cache=cache, queue=queue, opener=server
            ),
            (dl.DICOTOPO, "index"): lambda job: dl.handle_index(
                job, cache=cache, index=index
            ),
        },
    )


def test_download_then_index_through_worker(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    index = DicoTopoIndex(tmp_path / "dt.sqlite")
    server = FakeServer()
    assert len(dl.request_download(queue, ["62"])) == 1
    worker = _worker(queue, cache, index, server)
    assert worker.run_once() and worker.run_once()
    assert not worker.run_once()
    assert (cache / "dicotopo" / "DT62.xml").is_file()
    assert list(index.departments()) == ["62"]
    assert index.departments()["62"].endswith("+00:00")


def test_partial_download_is_never_indexed(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    index = DicoTopoIndex(tmp_path / "dt.sqlite")
    (cache / "dicotopo").mkdir(parents=True)
    (cache / "dicotopo" / "DT62.xml.part").write_bytes(b"<x")
    queue.enqueue(dl.DICOTOPO, "index", "DT62", {}, 0)
    worker = _worker(queue, cache, index, FakeServer())
    assert worker.run_once()
    assert index.departments() == {}
    assert queue.errors()[0].error


def test_missing_upstream_department_is_a_french_error(
    tmp_path: Path, queue: SourceQueue
) -> None:
    queue.enqueue(dl.DICOTOPO, "download", "DT75", {}, 0)
    job = queue.next_job()
    assert job is not None
    with pytest.raises(SourceError, match="absent de DicoTopo"):
        dl.handle_download(job, cache=tmp_path, queue=queue, opener=FakeServer())
    assert not (tmp_path / "dicotopo" / "DT75.xml.part").exists()


def test_coverage_cached_without_network(tmp_path: Path) -> None:
    server = FakeServer()
    assert dl.coverage(tmp_path, opener=server) == ["59", "62"]
    assert dl.coverage(tmp_path) == ["59", "62"]  # urlopen is blocked: cache only
    assert server.urls == [dl.CONTENTS_URL]


def test_coverage_unknown_without_cache_or_network(tmp_path: Path) -> None:
    assert dl.coverage(tmp_path) == []


def test_unknown_department_is_refused(queue: SourceQueue) -> None:
    for bad in ("20", "999", "96", "ab"):
        with pytest.raises(SourceError):
            dl.request_download(queue, [bad])
    with pytest.raises(SourceError):
        dl.request_download(queue, ["01"], covered=["59", "62"])
    assert queue.next_job() is None
    assert dl.request_download(queue, ["2a", "974"])  # well-formed fallback


def test_raw_url_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, queue: SourceQueue
) -> None:
    monkeypatch.setenv(dl.RAW_ENV, "http://127.0.0.1:8000/DT{dept}.xml")
    seen: list[str] = []

    def opener(request: urllib.request.Request, timeout: float) -> BinaryIO:
        seen.append(request.full_url)
        return io.BytesIO((FIXTURES / "DT62.xml").read_bytes())  # type: ignore[return-value]

    queue.enqueue(dl.DICOTOPO, "download", "DT62", {}, 0)
    job = queue.next_job()
    assert job is not None
    dl.handle_download(job, cache=tmp_path, queue=queue, opener=opener)
    assert seen == ["http://127.0.0.1:8000/DT62.xml"]


def test_remove_department(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    index = DicoTopoIndex(tmp_path / "dt.sqlite")
    server = FakeServer()
    dl.request_download(queue, ["62"])
    worker = _worker(queue, cache, index, server)
    worker.run_once()
    worker.run_once()
    dl.remove_department(cache, index, "62")
    assert index.departments() == {}
    assert not (cache / "dicotopo" / "DT62.xml").exists()
