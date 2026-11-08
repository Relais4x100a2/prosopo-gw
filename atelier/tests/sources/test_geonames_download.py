from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO

import pytest

from prosopo_gw_atelier.sources.base import SourceError
from prosopo_gw_atelier.sources.geonames import download as dl
from prosopo_gw_atelier.sources.geonames.index import GeoNamesIndex
from prosopo_gw_atelier.sources.queue import SourceQueue, Worker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "geonames"


class _Response(io.BytesIO):
    def __init__(self, data: bytes, headers: dict[str, str]) -> None:
        super().__init__(data)
        self.headers = headers


class FakeServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> BinaryIO:
        url = request.full_url
        self.requests.append((request.get_method(), url))
        name = url.rsplit("/", 1)[-1]
        path = FIXTURES / name
        if url != dl.DUMP_URL + name or not path.is_file():
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]
        data = path.read_bytes()
        headers = {
            "Content-Length": str(len(data)),
            "Last-Modified": "Sun, 08 Nov 2026 03:38:08 GMT",
        }
        return _Response(b"" if request.get_method() == "HEAD" else data, headers)  # type: ignore[return-value]


@pytest.fixture
def queue(tmp_path: Path) -> SourceQueue:
    return SourceQueue(tmp_path / "q.sqlite")


def _worker(
    queue: SourceQueue, cache: Path, index: GeoNamesIndex, server: FakeServer
) -> Worker:
    return Worker(
        queue,
        {
            (dl.GEONAMES, "download"): lambda job: dl.handle_download(
                job, cache=cache, opener=server
            ),
            (dl.GEONAMES, "index"): lambda job: dl.handle_index(
                job, cache=cache, index=index
            ),
        },
    )


def _drain(worker: Worker) -> int:
    count = 0
    while worker.run_once():
        count += 1
    return count


def test_country_download_then_index(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    index = GeoNamesIndex(tmp_path / "idx")
    server = FakeServer()
    assert len(dl.request_country(queue, "ca", cache=cache)) == 5
    assert _drain(_worker(queue, cache, index, server)) == 5
    assert queue.errors() == []
    assert index.countries() == {"CA": "2026-11-08"}
    assert (cache / "geonames" / "CA.zip").is_file()
    assert (cache / "geonames" / "CA.date").read_text() == "2026-11-08"


def test_common_files_downloaded_once(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    index = GeoNamesIndex(tmp_path / "idx")
    server = FakeServer()
    worker = _worker(queue, cache, index, server)
    dl.request_country(queue, "CA", cache=cache)
    _drain(worker)
    assert len(dl.request_country(queue, "GB", cache=cache)) == 2
    _drain(worker)
    fetched = [url.rsplit("/", 1)[-1] for _, url in server.requests]
    assert sorted(fetched) == sorted([*dl.COMMON_FILES, "CA.zip", "GB.zip"])
    assert set(index.countries()) == {"CA", "GB"}


def test_invalid_country_code_refused(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    for bad in ("../", "", "CAN", "C1", "ca/"):
        with pytest.raises(SourceError):
            dl.request_country(queue, bad, cache=cache)
    assert queue.next_job() is None
    # With countryInfo.txt cached, an unknown (well-formed) code is refused too.
    (cache / "geonames").mkdir(parents=True)
    (cache / "geonames" / "countryInfo.txt").write_bytes(
        (FIXTURES / "countryInfo.txt").read_bytes()
    )
    with pytest.raises(SourceError, match="inconnu"):
        dl.request_country(queue, "XX", cache=cache)
    assert queue.next_job() is None
    assert len(dl.request_country(queue, "gb", cache=cache)) == 4


def test_unknown_country_fails_in_the_worker(
    tmp_path: Path, queue: SourceQueue
) -> None:
    server = FakeServer()
    dl.request_country(queue, "XX")
    worker = _worker(queue, tmp_path / "cache", GeoNamesIndex(tmp_path / "idx"), server)
    _drain(worker)
    assert not (tmp_path / "cache" / "geonames" / "XX.zip.part").exists()
    # countryInfo.txt arrives first: the handler already knows XX is unknown.
    assert any("inconnu de GeoNames" in (j.error or "") for j in queue.errors())
    assert not (tmp_path / "cache" / "geonames" / "XX.zip").exists()
    server.requests.clear()
    queue.enqueue(dl.GEONAMES, "download", "YY.zip", {}, 0)
    job = queue.next_job()
    assert job is not None
    with pytest.raises(SourceError, match="absent de GeoNames"):
        dl.handle_download(job, cache=tmp_path / "other", opener=server)


def test_download_date_fallback_without_header(
    tmp_path: Path, queue: SourceQueue
) -> None:
    def opener(request: urllib.request.Request, timeout: float) -> BinaryIO:
        return io.BytesIO((FIXTURES / "CA.zip").read_bytes())  # type: ignore[return-value]

    queue.enqueue(dl.GEONAMES, "download", "CA.zip", {}, 0)
    job = queue.next_job()
    assert job is not None
    dl.handle_download(job, cache=tmp_path, opener=opener)
    stamp = (tmp_path / "geonames" / "CA.date").read_text()
    assert len(stamp) == 10 and stamp[4] == "-"


def test_remote_size() -> None:
    server = FakeServer()
    size = dl.remote_size(dl.DUMP_URL + "CA.zip", opener=server)
    assert size == (FIXTURES / "CA.zip").stat().st_size
    assert server.requests == [("HEAD", dl.DUMP_URL + "CA.zip")]
    assert dl.remote_size(dl.DUMP_URL + "ZZ.zip", opener=server) is None

    def broken(request: urllib.request.Request, timeout: float) -> BinaryIO:
        raise urllib.error.URLError("down")

    assert dl.remote_size(dl.DUMP_URL + "CA.zip", opener=broken) is None
    assert dl.remote_size(dl.DUMP_URL + "CA.zip") is None  # network blocked


def test_dump_url_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, queue: SourceQueue
) -> None:
    monkeypatch.setenv(dl.DUMP_ENV, "http://127.0.0.1:8000/dump/")
    seen: list[str] = []

    def opener(request: urllib.request.Request, timeout: float) -> BinaryIO:
        seen.append(request.full_url)
        return io.BytesIO(b"x")  # type: ignore[return-value]

    queue.enqueue(dl.GEONAMES, "download", "admin2Codes.txt", {}, 0)
    job = queue.next_job()
    assert job is not None
    dl.handle_download(job, cache=tmp_path, opener=opener)
    assert seen == ["http://127.0.0.1:8000/dump/admin2Codes.txt"]


@pytest.mark.parametrize("bad", ["ftp://x/", "http://x/dump", "file:///tmp/"])
def test_invalid_dump_override_is_ignored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, bad: str
) -> None:
    monkeypatch.setenv(dl.DUMP_ENV, bad)
    assert dl._dump_url() == dl.DUMP_URL
    assert dl.DUMP_ENV in caplog.text


def test_index_requires_complete_files(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    (cache / "geonames").mkdir(parents=True)
    (cache / "geonames" / "CA.zip.part").write_bytes(b"PK")
    queue.enqueue(dl.GEONAMES, "index", "CA", {}, 0)
    job = queue.next_job()
    assert job is not None
    with pytest.raises(SourceError, match="absent ou incomplet"):
        dl.handle_index(job, cache=cache, index=GeoNamesIndex(tmp_path / "idx"))


def test_remove_country(tmp_path: Path, queue: SourceQueue) -> None:
    cache = tmp_path / "cache"
    index = GeoNamesIndex(tmp_path / "idx")
    dl.request_country(queue, "CA", cache=cache)
    _drain(_worker(queue, cache, index, FakeServer()))
    dl.remove_country(cache, index, "ca", queue=queue)
    assert index.countries() == {}
    assert not (cache / "geonames" / "CA.zip").exists()
    assert not (cache / "geonames" / "CA.date").exists()
    assert (cache / "geonames" / "countryInfo.txt").is_file()
    with pytest.raises(SourceError):
        dl.remove_country(cache, index, "../")
