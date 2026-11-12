from __future__ import annotations

import io
import json
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

import pytest
from fastapi.testclient import TestClient

from prosopo_gw_atelier.project import Project
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.sources import DICOTOPO, GEONAMES, SourceRuntime
from prosopo_gw_atelier.sources.dicotopo import download as dl
from prosopo_gw_atelier.sources.queue import SourceQueue
from prosopo_gw_atelier.store.config import load_config
from prosopo_gw_atelier.store.registry import PlaceRegistry
from prosopo_gw_atelier.web.app import create_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HAMLET = "Fictimont, Hesdin-la-Forêt"


class FakeServer:
    calls = 0

    def __call__(self, request: urllib.request.Request, timeout: float) -> BinaryIO:
        url = request.full_url
        FakeServer.calls += 1
        if url == dl.CONTENTS_URL:
            entries = [{"name": f"DT{d}", "type": "dir"} for d in ("62", "59")]
            return io.BytesIO(json.dumps(entries).encode())  # type: ignore[return-value]
        if url == dl.RAW_URL.replace("{dept}", "62"):
            return io.BytesIO((FIXTURES / "dicotopo" / "DT62.xml").read_bytes())  # type: ignore[return-value]
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "data" / "referentiel.sqlite") as reg:
        yield reg


@pytest.fixture
def runtime(tmp_path: Path, ref: RefData) -> SourceRuntime:
    return SourceRuntime.build(tmp_path / "data", ref, opener=FakeServer())


@pytest.fixture
def client(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData, runtime: SourceRuntime
) -> TestClient:
    gw = tmp_path / "bases" / "lieux_dicotopo.gw"
    gw.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "lieux_dicotopo.gw", gw)
    project = Project.open(gw, registry, ref, tmp_path / "data" / "projets")
    app = create_app(project, registry, ref, sources=runtime, start_worker=False)
    return TestClient(app, base_url="http://127.0.0.1")


def drain(runtime: SourceRuntime) -> int:
    count = 0
    while runtime.worker.run_once():
        count += 1
    return count


def hamlet_id(client: TestClient) -> str:
    rows = client.get("/api/clusters").json()
    return next(r["id"] for r in rows if HAMLET in client_writings(client, r["id"]))


def client_writings(client: TestClient, cluster_id: str) -> list[str]:
    from urllib.parse import quote

    data = client.get(f"/api/clusters/{quote(cluster_id, safe='')}").json()
    return [w["text"] for w in data["writings"]]


def cluster(client: TestClient, cluster_id: str) -> dict[str, Any]:
    from urllib.parse import quote

    result: dict[str, Any] = client.get(
        f"/api/clusters/{quote(cluster_id, safe='')}"
    ).json()
    return result


def index_dicotopo(client: TestClient, runtime: SourceRuntime) -> None:
    assert client.post("/api/sources/dicotopo/download", json={"departments": ["62"]})
    drain(runtime)  # download, index, then the matches


def test_sources_status(client: TestClient, runtime: SourceRuntime) -> None:
    body = client.get("/api/sources").json()
    assert body["dicotopo"] == {
        "coverage": [],
        "coverage_known": False,
        "departments": [],
        "api_enabled": False,
    }
    assert FakeServer.calls == 0  # the status never reads the network
    dl.coverage(runtime.cache, opener=FakeServer())
    body = client.get("/api/sources").json()
    assert body["dicotopo"]["coverage"] == ["59", "62"]
    assert body["dicotopo"]["coverage_known"] is True
    assert body["queue"]["errors"] == []
    assert any("CC BY-NC-ND" in text for text in body["attributions"])
    index_dicotopo(client, runtime)
    (department,) = client.get("/api/sources").json()["dicotopo"]["departments"]
    assert department["code"] == "62"
    assert department["articles"] > 0
    assert set(department) == {"code", "name", "downloaded_at", "articles", "skipped"}


def test_request_download_enqueues(client: TestClient, runtime: SourceRuntime) -> None:
    response = client.post(
        "/api/sources/dicotopo/download", json={"departments": ["62"]}
    )
    assert response.status_code == 200
    assert response.json() == {"queued": ["62"]}
    assert runtime.queue.counts()[DICOTOPO]["pending"] >= 1
    assert any(
        j.kind == "download" for j in [runtime.queue.next_job()] if j is not None
    )


def test_unknown_department_400(client: TestClient, runtime: SourceRuntime) -> None:
    response = client.post(
        "/api/sources/dicotopo/download", json={"departments": ["ZZ"]}
    )
    assert response.status_code == 400
    assert "Département inconnu" in response.json()["detail"]
    assert client.delete("/api/sources/dicotopo/departments/ZZ").status_code == 400
    assert runtime.queue.counts().get(DICOTOPO) is None


def test_toggle_api_writes_config(client: TestClient, runtime: SourceRuntime) -> None:
    response = client.put("/api/sources/dicotopo/api", json={"enabled": True})
    assert response.json() == {"api_enabled": True}
    assert load_config(runtime.config_path).dicotopo_api is True
    assert client.get("/api/sources").json()["dicotopo"]["api_enabled"] is True
    client.put("/api/sources/dicotopo/api", json={"enabled": False})
    assert load_config(runtime.config_path).dicotopo_api is False


def test_delete_department_and_cache_clear_and_retry(
    client: TestClient, runtime: SourceRuntime
) -> None:
    index_dicotopo(client, runtime)
    assert client.delete("/api/sources/dicotopo/departments/62").status_code == 200
    assert client.get("/api/sources").json()["dicotopo"]["departments"] == []
    assert client.post("/api/sources/queue/retry").json()["errors"] == []
    assert (
        client.post("/api/sources/cache/clear", json={"source": "nope"}).status_code
        == 400
    )
    cleared = client.post("/api/sources/cache/clear", json={"source": DICOTOPO})
    assert cleared.json() == {"cleared": DICOTOPO}
    assert runtime.queue.counts().get(DICOTOPO) is None


def test_cluster_view_bumps_priority(
    client: TestClient, runtime: SourceRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    touched: list[str] = []
    project = client.app.state.atelier.project  # type: ignore[attr-defined]
    monkeypatch.setattr(project, "touch", touched.append)
    first = client.get("/api/clusters").json()[0]["id"]
    cluster(client, first)
    assert touched == [first]
    assert client.get("/api/clusters/absent").status_code == 404
    assert touched == [first]


def test_worker_not_started_in_tests(
    client: TestClient, runtime: SourceRuntime
) -> None:
    with client:
        assert not runtime.worker.running
    assert not runtime.worker.running


def test_worker_starts_and_stops_with_the_app(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData, runtime: SourceRuntime
) -> None:
    gw = tmp_path / "bases" / "lieux_dicotopo.gw"
    gw.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "lieux_dicotopo.gw", gw)
    project = Project.open(gw, registry, ref, tmp_path / "data" / "projets")
    app = create_app(project, registry, ref, sources=runtime)
    with TestClient(app, base_url="http://127.0.0.1"):
        assert runtime.worker.running
    assert not runtime.worker.running


def proposed_detail(client: TestClient, runtime: SourceRuntime) -> dict[str, Any]:
    index_dicotopo(client, runtime)
    client.get("/api/clusters")  # the project enqueues the matches it can now ask
    drain(runtime)
    data = cluster(client, hamlet_id(client))
    assert data["pending_sources"] == []
    assert data["failed_sources"] == []
    assert any(lv["origin"] == "dicotopo" for lv in data["levels"])
    return data


def test_validate_saves_only_non_proposed_levels(
    client: TestClient, runtime: SourceRuntime, registry: PlaceRegistry
) -> None:
    data = proposed_detail(client, runtime)
    from urllib.parse import quote

    body = {
        "levels": data["levels"],
        "postal_code": data["postal_code"],
        "checked": [w["text"] for w in data["writings"]],
    }
    response = client.post(
        f"/api/clusters/{quote(data['id'], safe='')}/validate", json=body
    )
    assert response.status_code == 200, response.text
    place = registry.place(response.json()["place_id"])
    assert all(lv.origin != "dicotopo" for lv in place.levels)
    assert all(lv.status != "proposed" for lv in place.levels)


def test_accept_source_proposal_on_place_then_undo(
    client: TestClient, runtime: SourceRuntime, registry: PlaceRegistry
) -> None:
    data = proposed_detail(client, runtime)
    from urllib.parse import quote

    proposed = next(lv for lv in data["levels"] if lv["origin"] == "dicotopo")
    base = [lv for lv in data["levels"] if lv["origin"] != "dicotopo"]
    validate = {
        "levels": base,
        "postal_code": data["postal_code"],
        "checked": [w["text"] for w in data["writings"]],
    }
    place_id = client.post(
        f"/api/clusters/{quote(data['id'], safe='')}/validate", json=validate
    ).json()["place_id"]
    before = [lv.name for lv in registry.place(place_id).levels]
    url = f"/api/places/{place_id}/source-proposals/accept"
    response = client.post(url, json={"level": proposed})
    assert response.status_code == 200, response.text
    levels = response.json()["levels"]
    assert any(lv["identifier"] == proposed["identifier"] for lv in levels)
    assert all(lv["status"] == "validated" for lv in levels)
    assert client.post("/api/undo").json() == {"action": "correct"}
    assert [lv.name for lv in registry.place(place_id).levels] == before
    missing = client.post(
        "/api/places/place-inconnu/source-proposals/accept", json={"level": proposed}
    )
    assert missing.status_code == 404
    bad = client.post(url, json={"level": {**proposed, "rank": 99}})
    assert bad.status_code == 400


def test_refuse_source_proposal(client: TestClient, registry: PlaceRegistry) -> None:
    body = {
        "subject": "writing:" + HAMLET,
        "source": DICOTOPO,
        "identifier": "P90000002",
    }
    first = client.post("/api/source-proposals/refuse", json=body)
    assert first.status_code == 200
    assert isinstance(first.json()["entry_id"], int)
    assert client.post("/api/source-proposals/refuse", json=body).json() == {
        "entry_id": None
    }
    bad = client.post("/api/source-proposals/refuse", json={**body, "subject": "x:1"})
    assert bad.status_code == 400
    assert client.post("/api/undo").json() == {"action": "correct"}
    assert client.post("/api/source-proposals/refuse", json=body).json()["entry_id"]


def test_sources_unavailable_without_runtime(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData
) -> None:
    gw = tmp_path / "bases" / "lieux_dicotopo.gw"
    gw.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "lieux_dicotopo.gw", gw)
    project = Project.open(gw, registry, ref, tmp_path / "data" / "projets")
    plain = TestClient(create_app(project, registry, ref), base_url="http://127.0.0.1")
    assert plain.get("/api/sources").status_code == 503


def test_coverage_refresh_is_background_and_negative_cached(
    client: TestClient, runtime: SourceRuntime
) -> None:
    def failing(request: urllib.request.Request, timeout: float) -> BinaryIO:
        raise urllib.error.URLError("offline")

    runtime.opener = failing
    assert runtime.refresh_coverage() is True
    for _ in range(100):
        if (runtime.cache / DICOTOPO / "coverage.failed").exists():
            break
        time.sleep(0.05)
    assert (runtime.cache / DICOTOPO / "coverage.failed").exists()
    assert runtime.refresh_coverage() is False  # not retried within the hour
    assert client.post("/api/sources/dicotopo/coverage/refresh").json() == {
        "started": False
    }


def test_delete_department_forgets_its_proposals(
    client: TestClient, runtime: SourceRuntime
) -> None:
    data = proposed_detail(client, runtime)
    assert client.delete("/api/sources/dicotopo/departments/62").status_code == 200
    after = cluster(client, data["id"])
    assert all(lv["origin"] != "dicotopo" for lv in after["levels"])


def test_download_validation(client: TestClient) -> None:
    assert (
        client.post(
            "/api/sources/dicotopo/download", json={"departments": []}
        ).status_code
        == 400
    )
    twice = client.post(
        "/api/sources/dicotopo/download", json={"departments": ["62", " 62"]}
    )
    assert twice.json() == {"queued": ["62"]}


def test_accept_requires_a_source_level(
    client: TestClient, runtime: SourceRuntime
) -> None:
    level = {"rank": 0, "name": "X", "origin": "manual", "identifier": "P1"}
    response = client.post(
        "/api/places/any/source-proposals/accept", json={"level": level}
    )
    assert response.status_code == 400
    level = {"rank": 0, "name": "X", "origin": "dicotopo"}
    assert (
        client.post(
            "/api/places/any/source-proposals/accept", json={"level": level}
        ).status_code
        == 400
    )


def test_attribution_names_the_upstream_licence(client: TestClient) -> None:
    attributions = client.get("/api/sources").json()["attributions"]
    assert any("CC BY-NC-ND 3.0 FR" in line for line in attributions)


def test_stale_dicotopo_results_are_dropped_on_start(
    tmp_path: Path, ref: RefData
) -> None:
    cache = tmp_path / "data" / "cache"
    cache.mkdir(parents=True)
    old = SourceQueue(cache / "queue.sqlite")  # a cache from before versioning
    old.store_result(DICOTOPO, "old", [])
    old.store_result(GEONAMES, "kept", [])
    runtime = SourceRuntime.build(tmp_path / "data", ref, opener=FakeServer())
    assert runtime.queue.result(DICOTOPO, "old") is None
    assert runtime.queue.result(GEONAMES, "kept") == []
    runtime.queue.store_result(DICOTOPO, "new", [])
    again = SourceRuntime.build(tmp_path / "data", ref, opener=FakeServer())
    assert again.queue.result(DICOTOPO, "new") == []


def test_detail_names_dicotopo_departments_until_indexed(
    client: TestClient, runtime: SourceRuntime
) -> None:
    client.get("/api/clusters")
    assert cluster(client, hamlet_id(client))["dicotopo_missing"] == ["62"]
    data = proposed_detail(client, runtime)
    assert data["dicotopo_missing"] == []
