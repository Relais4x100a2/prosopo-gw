from __future__ import annotations

import io
import json
import logging
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import pytest

from prosopo_gw_atelier.export.archive import build_archive
from prosopo_gw_atelier.places.levels import Level
from prosopo_gw_atelier.project import Project
from prosopo_gw_atelier.refdata import load_refdata
from prosopo_gw_atelier.sources.base import (
    CredentialsRejected,
    LevelQuery,
    QuotaReached,
    SourceCandidate,
    SourceError,
)
from prosopo_gw_atelier.sources.geonames.index import GeoNamesIndex
from prosopo_gw_atelier.sources.geonames.source import GEONAMES, GeoNamesSource
from prosopo_gw_atelier.sources.queue import (
    SourceQueue,
    Worker,
    handle_match,
    match_payload,
)
from prosopo_gw_atelier.store.config import LocalConfig
from prosopo_gw_atelier.store.registry import PlaceRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GN = FIXTURES / "geonames"
SECRET = "user-secret-123"
NOON = datetime(2026, 11, 8, 12, 30, tzinfo=UTC).timestamp()
NEXT_HOUR = datetime(2026, 11, 8, 13, 0, tzinfo=UTC).timestamp()
MIDNIGHT = datetime(2026, 11, 9, 0, 0, tzinfo=UTC).timestamp()


class _Response(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers: dict[str, str] = {}


class FakeApi:
    """Serves GeoNames JSON; ``plan`` items are consumed in order (else ``default``)."""

    def __init__(self, default: object = None) -> None:
        self.urls: list[str] = []
        self.plan: list[object] = []
        self.default: object = default if default is not None else {"geonames": []}

    def __call__(self, request: urllib.request.Request, timeout: float) -> BinaryIO:
        url = request.full_url
        self.urls.append(url)
        item = self.plan.pop(0) if self.plan else self.default
        if isinstance(item, BaseException):
            raise item
        return _Response(json.dumps(item).encode())  # type: ignore[return-value]

    def params(self, n: int = -1) -> dict[str, list[str]]:
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.urls[n]).query)


class NoWait:
    def __init__(self) -> None:
        self.calls = 0

    def wait(self) -> None:
        self.calls += 1


def _entry(geonameid: int = 5000001, name: str = "Nowhere") -> dict[str, object]:
    return {
        "geonameId": geonameid,
        "name": name,
        "lat": "46.5",
        "lng": "-72.25",
        "fcl": "P",
        "fcode": "PPL",
        "countryCode": "ZZ",
        "adminName1": "Region Un",
        "adminId1": 5000100,
        "adminName2": "Region Deux",
        "adminId2": 5000200,
        "population": 10,
    }


@pytest.fixture
def index(tmp_path: Path) -> GeoNamesIndex:
    idx = GeoNamesIndex(tmp_path / "geonames")
    idx.build(
        "CA",
        GN / "CA.zip",
        GN / "admin1CodesASCII.txt",
        GN / "admin2Codes.txt",
        "2026-11-08",
    )
    return idx


def make(
    index: GeoNamesIndex,
    tmp_path: Path,
    api: FakeApi,
    *,
    username: str | None = SECRET,
    clock: float = NOON,
) -> GeoNamesSource:
    return GeoNamesSource(
        index,
        config=LocalConfig(geonames_username=username),
        counter_path=tmp_path / "cache" / "api_counter.json",
        opener=api,
        limiter=NoWait(),  # type: ignore[arg-type]
        clock=lambda: clock,
    )


def q(name: str, country: str | None = "CA") -> LevelQuery:
    return LevelQuery(name=name, country=country)


def test_local_hit_makes_no_request(index: GeoNamesIndex, tmp_path: Path) -> None:
    api = FakeApi()
    source = make(index, tmp_path, api)
    found = source.search(q("Winnipeg"))
    assert [c.identifier for c in found] == ["9000001"]
    assert found[0].source_text == "GeoNames 2026-11-08"
    assert found[0].latitude == pytest.approx(49.88)
    assert [p.name for p in found[0].parents] == ["Manitoba"]
    assert api.urls == []
    assert not (tmp_path / "cache" / "api_counter.json").exists()


def test_api_only_with_username(index: GeoNamesIndex, tmp_path: Path) -> None:
    api = FakeApi({"geonames": [_entry()]})
    source = make(index, tmp_path, api, username=None)
    assert not source.can_answer(q("Nowhere", "ZZ"))
    assert source.search(q("Nowhere", "ZZ")) == []
    assert source.search(q("Nowhere", "CA")) == []  # indexed country, local miss
    assert api.urls == []
    with_user = make(index, tmp_path, api)
    assert with_user.can_answer(q("Nowhere", "ZZ"))
    found = with_user.search(q("Nowhere", "ZZ"))
    assert [c.identifier for c in found] == ["5000001"]
    assert found[0].source_text == "GeoNames 2026-11-08"
    assert [(p.rank, p.name, p.identifier) for p in found[0].parents] == [
        (1, "Region Deux", "5000200"),
        (2, "Region Un", "5000100"),
    ]
    params = api.params()
    assert params["name_equals"] == ["Nowhere"]
    assert params["country"] == ["ZZ"]
    assert params["featureClass"] == ["P", "A"]
    assert api.urls[0].startswith("https://secure.geonames.org/searchJSON?")
    assert not with_user.can_answer(q("Nowhere", None))


def test_api_only_when_local_misses(index: GeoNamesIndex, tmp_path: Path) -> None:
    api = FakeApi({"geonames": [_entry(name="Nowhere")]})
    source = make(index, tmp_path, api)
    assert source.covers(q("Winnipeg")) and not source.covers(q("Winnipeg", "ZZ"))
    assert source.search(q("Winnipeg"))
    assert api.urls == []
    assert [c.name for c in source.search(q("Nowhere"))] == ["Nowhere"]
    assert len(api.urls) == 1


def test_article_local_then_api(index: GeoNamesIndex, tmp_path: Path) -> None:
    api = FakeApi(_entry(5000009, "Elsewhere"))
    source = make(index, tmp_path, api)
    local = source.article("9000002")
    assert local is not None and local.name == "Manitoba"
    assert api.urls == []
    remote = source.article("5000009")
    assert remote is not None and remote.name == "Elsewhere"
    assert api.urls[0].startswith("https://secure.geonames.org/getJSON?")
    assert api.params()["geonameId"] == ["5000009"]
    assert source.article("abc") is None
    assert make(index, tmp_path, api, username=None).article("5000009") is None


def test_daily_counter_persists(index: GeoNamesIndex, tmp_path: Path) -> None:
    counter = tmp_path / "cache" / "api_counter.json"
    counter.parent.mkdir()
    counter.write_text(json.dumps({"date": "2026-11-08", "count": 9999}))
    api = FakeApi()
    source = make(index, tmp_path, api)
    source.search(q("Nowhere", "ZZ"))
    assert json.loads(counter.read_text()) == {"date": "2026-11-08", "count": 10000}
    with pytest.raises(QuotaReached) as raised:
        make(index, tmp_path, api).search(q("Nowhere", "ZZ"))  # new instance, same file
    assert raised.value.retry_at == MIDNIGHT
    assert len(api.urls) == 1
    # a new UTC day resets the counter
    tomorrow = make(index, tmp_path, api, clock=MIDNIGHT + 5)
    tomorrow.search(q("Nowhere", "ZZ"))
    assert json.loads(counter.read_text()) == {"date": "2026-11-09", "count": 1}


@pytest.mark.parametrize(
    ("code", "retry"), [(19, NEXT_HOUR), (18, MIDNIGHT), (20, MIDNIGHT)]
)
def test_status_codes_raise_quota(
    index: GeoNamesIndex, tmp_path: Path, code: int, retry: float
) -> None:
    api = FakeApi({"status": {"value": code, "message": f"for {SECRET}"}})
    with pytest.raises(QuotaReached) as raised:
        make(index, tmp_path, api).search(q("Nowhere", "ZZ"))
    assert raised.value.retry_at == retry
    assert f"code {code}" in str(raised.value)
    assert SECRET not in str(raised.value)


def test_http_429_pauses_one_hour(index: GeoNamesIndex, tmp_path: Path) -> None:
    err = urllib.error.HTTPError("https://x/?username=" + SECRET, 429, "x", None, None)  # type: ignore[arg-type]
    with pytest.raises(QuotaReached) as raised:
        make(index, tmp_path, _failing(err)).search(q("Nowhere", "ZZ"))
    assert raised.value.retry_at == NOON + 3600


def _failing(err: BaseException) -> FakeApi:
    api = FakeApi()
    api.plan = [err]
    return api


def test_api_quota_pauses_geonames_only(index: GeoNamesIndex, tmp_path: Path) -> None:
    api = FakeApi({"status": {"value": 19, "message": "hourly limit"}})
    source = make(index, tmp_path, api)
    queue = SourceQueue(tmp_path / "sources.sqlite", clock=lambda: NOON)
    gn_job = queue.enqueue(
        GEONAMES, "match", "k1", match_payload(q("Nowhere", "ZZ")), 5
    )
    other = queue.enqueue("dicotopo", "match", "k2", {}, 1)
    done: list[str] = []
    worker = Worker(
        queue,
        {
            (GEONAMES, "match"): lambda job: handle_match(
                job, source=source, queue=queue
            ),
            ("dicotopo", "match"): lambda job: done.append(job.key),
        },
    )
    assert worker.run_once() is True  # GeoNames job: paused, not failed
    assert queue.paused_until(GEONAMES) == NEXT_HOUR
    assert queue.paused_until("dicotopo") is None
    job = queue.next_job()
    assert job is not None and job.id == other  # DicoTopo flows, GeoNames is skipped
    queue.finish(job.id)
    assert queue.errors() == []
    counts = queue.counts()[GEONAMES]
    assert counts["pending"] == 1 and counts["failed"] == 0
    later = SourceQueue(tmp_path / "sources.sqlite", clock=lambda: NEXT_HOUR + 1)
    resumed = later.next_job()  # the pause is persisted and expires
    assert resumed is not None and resumed.id == gn_job and resumed.attempts == 0


def test_pause_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite"
    SourceQueue(path, clock=lambda: NOON).pause("geonames", NEXT_HOUR)
    assert SourceQueue(path, clock=lambda: NOON).paused_until("geonames") == NEXT_HOUR
    assert SourceQueue(path, clock=lambda: NEXT_HOUR).paused_until("geonames") is None


def _chain(exc: BaseException | None) -> list[str]:
    out: list[str] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        out += [
            str(exc),
            repr(exc),
            str(getattr(exc, "url", "")),
            str(getattr(exc, "filename", "")),
        ]
        out += [str(a) for a in exc.args]
        exc = exc.__cause__ or exc.__context__
    return out


def test_username_never_leaks(
    index: GeoNamesIndex, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    url = f"https://secure.geonames.org/searchJSON?username={SECRET}"
    api = FakeApi()
    api.plan = [
        urllib.error.HTTPError(url, 500, "boom", None, None),  # type: ignore[arg-type]
        urllib.error.HTTPError(url, 404, "nope", None, None),  # type: ignore[arg-type]
        urllib.error.URLError(f"unreachable {url}"),
        {"status": {"value": 10, "message": f"user {SECRET} does not exist"}},
        {"status": {"value": 12, "message": f"error for {SECRET}"}},
        urllib.error.HTTPError(url, 429, "slow", None, None),  # type: ignore[arg-type]
        {"geonames": [_entry()]},
    ]
    source = make(index, tmp_path, api)
    errors: list[BaseException] = []
    for _ in range(6):
        with pytest.raises(SourceError) as raised:
            source.search(q("Nowhere", "ZZ"))
        errors.append(raised.value)
    for error in errors:
        assert error.__cause__ is None and error.__context__ is None
        assert all(SECRET not in text for text in _chain(error))

    queue = SourceQueue(tmp_path / "sources.sqlite", clock=lambda: NOON)
    key = q("Nowhere", "ZZ").key()
    queue.enqueue(GEONAMES, "match", key, match_payload(q("Nowhere", "ZZ")), 5)
    worker = Worker(
        queue,
        {
            (GEONAMES, "match"): lambda job: handle_match(
                job, source=source, queue=queue
            )
        },
    )
    assert worker.run_once()
    candidates = queue.results(GEONAMES, [key])[key]
    assert candidates and isinstance(candidates[0], SourceCandidate)

    registry_path = tmp_path / "data" / "referentiel.sqlite"
    gw = tmp_path / "bases" / "lieux_varies.gw"
    gw.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "lieux_varies.gw", gw)
    with PlaceRegistry(registry_path) as registry:
        registry.validate(
            ["Nowhere"],
            [
                Level(
                    0,
                    candidates[0].name,
                    identifier=candidates[0].identifier,
                    source=candidates[0].source_text,
                    origin="geonames",
                )
            ],
            None,
            None,
            project="p",
        )
        ref = load_refdata(FIXTURES / "refdata_mini")
        project = Project.open(gw, registry, ref, tmp_path / "data" / "projects")
        archive = build_archive(project, registry, ref, datetime(2026, 11, 8, 12, 0))

    files = [
        p for p in tmp_path.rglob("*") if p.is_file() and "fixtures" not in p.parts
    ]
    assert any(p.name == "api_counter.json" for p in files)
    assert any(p.name.startswith("sources.sqlite") for p in files)
    for path in files:
        assert SECRET.encode() not in path.read_bytes(), path
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for name in zf.namelist():
            assert SECRET.encode() not in zf.read(name), name
    assert SECRET not in caplog.text
    for record in caplog.records:
        assert SECRET not in repr(record.args)


def test_pause_only_holds_match_jobs(tmp_path: Path) -> None:
    queue = SourceQueue(tmp_path / "q.sqlite", clock=lambda: NOON)
    queue.pause(GEONAMES, NEXT_HOUR)
    queue.enqueue(GEONAMES, "match", "m", {}, 9)
    download = queue.enqueue(GEONAMES, "download", "d", {}, 1)
    job = queue.next_job()
    assert job is not None and job.id == download
    assert queue.next_job() is None


def test_pause_never_shortens(tmp_path: Path) -> None:
    queue = SourceQueue(tmp_path / "q.sqlite", clock=lambda: NOON)
    queue.pause(GEONAMES, MIDNIGHT)
    queue.pause(GEONAMES, NEXT_HOUR)
    assert queue.paused_until(GEONAMES) == MIDNIGHT
    queue.pause(GEONAMES, MIDNIGHT + 10)
    assert queue.paused_until(GEONAMES) == MIDNIGHT + 10


def test_sync_api_respects_pause(index: GeoNamesIndex, tmp_path: Path) -> None:
    queue = SourceQueue(tmp_path / "q.sqlite", clock=lambda: NOON)
    queue.pause(GEONAMES, NEXT_HOUR)
    api = FakeApi({"geonames": [_entry()]})
    source = GeoNamesSource(
        index,
        config=LocalConfig(geonames_username=SECRET),
        counter_path=tmp_path / "cache" / "api_counter.json",
        opener=api,
        limiter=NoWait(),  # type: ignore[arg-type]
        clock=lambda: NOON,
        queue=queue,
    )
    with pytest.raises(QuotaReached) as raised:
        source.search(q("Nowhere", "ZZ"))
    assert raised.value.retry_at == NEXT_HOUR
    with pytest.raises(QuotaReached):
        source.article("5000009")
    assert api.urls == []
    assert source.search(q("Winnipeg"))  # local answers still work


def test_hostile_username_is_one_parameter(
    index: GeoNamesIndex, tmp_path: Path
) -> None:
    hostile = "a&username=b#"
    api = FakeApi()
    make(index, tmp_path, api, username=hostile).search(q("Nowhere", "ZZ"))
    params = api.params()
    assert params["username"] == [hostile]
    assert len(urllib.parse.urlparse(api.urls[0]).query.split("&username=")) == 2


def test_rejected_username_holds_geonames_matches(
    index: GeoNamesIndex, tmp_path: Path
) -> None:
    """Code 10 (unknown user, web service off): matches wait, nothing fails."""
    api = FakeApi({"status": {"value": 10, "message": f"user {SECRET} unknown"}})
    queue = SourceQueue(tmp_path / "sources.sqlite", clock=lambda: NOON)
    source = GeoNamesSource(
        index,
        config=LocalConfig(geonames_username=SECRET),
        counter_path=tmp_path / "cache" / "api_counter.json",
        opener=api,
        limiter=NoWait(),  # type: ignore[arg-type]
        clock=lambda: NOON,
        queue=queue,
    )
    with pytest.raises(CredentialsRejected) as raised:
        make(index, tmp_path, api).search(q("Nowhere", "ZZ"))
    assert "code 10" in str(raised.value) and SECRET not in str(raised.value)
    first = queue.enqueue(GEONAMES, "match", "k1", match_payload(q("Nowhere", "ZZ")), 5)
    queue.enqueue(GEONAMES, "match", "k2", match_payload(q("Ailleurs", "ZZ")), 4)
    failed = queue.enqueue(GEONAMES, "match", "k3", {}, 1)
    queue.fail(failed, "ancienne erreur", permanent=True)
    download = queue.enqueue(GEONAMES, "download", "d", {}, 0)
    worker = Worker(
        queue,
        {
            (GEONAMES, "match"): lambda job: handle_match(
                job, source=source, queue=queue
            ),
            (GEONAMES, "download"): lambda job: None,
        },
    )
    assert worker.run_once() is True
    assert queue.credentials_rejected(GEONAMES)
    assert queue.paused_until(GEONAMES) is None  # not a quota pause
    requests = len(api.urls)
    job = queue.next_job()  # the matches wait, the download flows
    assert job is not None and job.id == download
    queue.finish(job.id)
    assert queue.next_job() is None
    assert len(api.urls) == requests
    counts = queue.counts()[GEONAMES]
    assert (counts["pending"], counts["failed"]) == (2, 1)
    with pytest.raises(CredentialsRejected):  # a direct call asks nothing either
        source.search(q("Nowhere", "ZZ"))
    assert len(api.urls) == requests
    assert source.search(q("Winnipeg"))  # local answers still work
    # A new user name lifts the hold and retries the failed matches.
    queue.clear_credentials_rejection(GEONAMES, retry_failed=True)
    assert not queue.credentials_rejected(GEONAMES)
    resumed = queue.next_job()
    assert resumed is not None and resumed.id == first and resumed.attempts == 0
    assert queue.counts()[GEONAMES]["failed"] == 0
    assert all(SECRET not in (j.error or "") for j in queue.errors())


def test_credentials_rejection_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite"
    SourceQueue(path).reject_credentials(GEONAMES)
    assert SourceQueue(path).credentials_rejected(GEONAMES)
    assert not SourceQueue(path).credentials_rejected("dicotopo")
    SourceQueue(path).clear_credentials_rejection(GEONAMES)
    assert not SourceQueue(path).credentials_rejected(GEONAMES)
