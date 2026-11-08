"""HTTP download helper: safe writes, size limit, French errors, no network."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO

import pytest

from prosopo_gw_atelier.sources.base import SourceError
from prosopo_gw_atelier.sources.fetch import USER_AGENT, download, get_json


class _Body(io.BytesIO):
    """Body that can fail after a given number of bytes."""

    def __init__(self, data: bytes, fail_after: int | None = None) -> None:
        super().__init__(data)
        self.fail_after = fail_after

    def read(self, size: int | None = -1) -> bytes:
        if self.fail_after is not None and self.tell() >= self.fail_after:
            raise OSError("connection reset")
        return super().read(size)


def _opener(body: BinaryIO, seen: list[urllib.request.Request] | None = None):
    def opener(request: urllib.request.Request, timeout: float) -> BinaryIO:
        if seen is not None:
            seen.append(request)
        return body

    return opener


def _raising(exc: Exception):
    def opener(request: urllib.request.Request, timeout: float) -> BinaryIO:
        raise exc

    return opener


def test_download_writes_then_renames(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "data.zip"
    size = download("http://x/a", target, opener=_opener(_Body(b"x" * 200_000)))
    assert size == 200_000
    assert target.read_bytes() == b"x" * 200_000
    assert not target.with_suffix(".zip.part").exists()


def test_failed_download_leaves_no_file(tmp_path: Path) -> None:
    target = tmp_path / "data.zip"
    body = _Body(b"x" * 200_000, fail_after=70_000)
    with pytest.raises(SourceError, match="Téléchargement impossible"):
        download("http://x/a", target, opener=_opener(body))
    assert not target.exists()
    assert not target.with_suffix(".zip.part").exists()


def test_max_bytes_aborts(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    with pytest.raises(SourceError, match="Téléchargement impossible"):
        download(
            "http://x/a", target, opener=_opener(_Body(b"x" * 5000)), max_bytes=1000
        )
    assert not target.exists()
    assert not target.with_suffix(".bin.part").exists()


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x/a", code, "err", None, None)  # type: ignore[arg-type]


def test_http_error_becomes_source_error(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="indisponible"):
        download("http://x/a", tmp_path / "a", opener=_raising(_http_error(500)))
    with pytest.raises(SourceError, match="limite"):
        download("http://x/a", tmp_path / "a", opener=_raising(_http_error(429)))
    with pytest.raises(SourceError, match="réseau"):
        download(
            "http://x/a", tmp_path / "a", opener=_raising(urllib.error.URLError("dns"))
        )
    with pytest.raises(SourceError, match="réseau"):
        download("http://x/a", tmp_path / "a", opener=_raising(TimeoutError()))
    assert not (tmp_path / "a").exists()


def test_user_agent_sent(tmp_path: Path) -> None:
    seen: list[urllib.request.Request] = []
    download("http://x/a", tmp_path / "a", opener=_opener(_Body(b"ok"), seen))
    assert seen[0].get_header("User-agent") == USER_AGENT
    assert USER_AGENT.startswith("prosopo-gw-atelier/")
    assert "(+https://github.com/Relais4x100a2/prosopo-gw)" in USER_AGENT
    assert "@" not in USER_AGENT


def test_get_json(tmp_path: Path) -> None:
    body = _Body(json.dumps({"a": 1}).encode())
    assert get_json("http://x/a", opener=_opener(body)) == {"a": 1}
    with pytest.raises(SourceError):
        get_json("http://x/a", opener=_opener(_Body(b"not json")))
    with pytest.raises(SourceError):
        get_json("http://x/a", opener=_raising(_http_error(500)))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/a", "/etc/passwd"])
def test_non_http_scheme_refused(tmp_path: Path, url: str) -> None:
    calls: list[urllib.request.Request] = []
    opener = _opener(_Body(b"x"), calls)
    target = tmp_path / "a.bin"
    with pytest.raises(SourceError, match="schéma"):
        download(url, target, opener=opener)
    with pytest.raises(SourceError, match="schéma"):
        get_json(url, opener=opener)
    assert calls == []
    assert not target.exists()
    assert not target.with_suffix(".bin.part").exists()


def test_max_bytes_boundary(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    assert (
        download("http://x/a", target, opener=_opener(_Body(b"x" * 100)), max_bytes=100)
        == 100
    )
    with pytest.raises(SourceError):
        download(
            "http://x/a",
            tmp_path / "b.bin",
            opener=_opener(_Body(b"x" * 101)),
            max_bytes=100,
        )


def test_failed_download_keeps_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"old")
    body = _Body(b"x" * 200_000, fail_after=70_000)
    with pytest.raises(SourceError):
        download("http://x/a", target, opener=_opener(body))
    assert target.read_bytes() == b"old"
    assert not target.with_suffix(".bin.part").exists()


def test_content_length_aborts_early(tmp_path: Path) -> None:
    class Big(_Body):
        headers = {"Content-Length": "5000"}  # noqa: RUF012
        reads = 0

        def read(self, size: int | None = -1) -> bytes:
            Big.reads += 1
            return super().read(size)

    body = Big(b"x" * 5000)
    with pytest.raises(SourceError, match="volumineux"):
        download("http://x/a", tmp_path / "a", opener=_opener(body), max_bytes=1000)
    assert Big.reads == 0


def test_get_json_size_cap() -> None:
    big = b'"' + b"x" * (5 * 1024 * 1024) + b'"'
    with pytest.raises(SourceError, match="volumineuse"):
        get_json("http://x/a", opener=_opener(_Body(big)))


def test_incomplete_read_is_french(tmp_path: Path) -> None:
    import http.client

    with pytest.raises(SourceError, match="incomplète"):
        download(
            "http://x/a",
            tmp_path / "a",
            opener=_raising(http.client.IncompleteRead(b"")),
        )
