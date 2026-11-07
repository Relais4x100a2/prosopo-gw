import io
import json
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from prosopo_gw_atelier.project import Project
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store.exchange import export_registry
from prosopo_gw_atelier.store.registry import PlaceRegistry
from prosopo_gw_atelier.web import app as web_app
from prosopo_gw_atelier.web.app import create_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROUBAIX = "insee:59512"
SPECIAL = 'Paris / Seine ? #1 "bis"'


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "data" / "referentiel.sqlite") as reg:
        yield reg


def open_project(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData, name: str
) -> Project:
    gw = tmp_path / "bases" / name
    gw.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / name, gw)
    return Project.open(gw, registry, ref, tmp_path / "data" / "projets")


def make_client(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData, name: str
) -> TestClient:
    project = open_project(tmp_path, registry, ref, name)
    return TestClient(create_app(project, registry, ref), base_url="http://127.0.0.1")


@pytest.fixture
def client(tmp_path: Path, registry: PlaceRegistry, ref: RefData) -> TestClient:
    return make_client(tmp_path, registry, ref, "lieux_varies.gw")


def cluster_url(cluster_id: str, action: str = "") -> str:
    url = f"/api/clusters/{quote(cluster_id, safe='')}"
    return f"{url}/{action}" if action else url


def detail(client: TestClient, cluster_id: str) -> dict[str, Any]:
    response = client.get(cluster_url(cluster_id))
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def writings_of(data: dict[str, Any]) -> list[str]:
    return [w["text"] for w in data["writings"]]


# --- project ------------------------------------------------------------------


def test_project_summary(client: TestClient, ref: RefData) -> None:
    response = client.get("/api/project")
    assert response.status_code == 200
    data = response.json()
    assert data["gw_name"] == "lieux_varies.gw"
    assert data["gw_changed"] is False
    assert data["counts"] == {
        "total": 8,
        "todo": 8,
        "validated": 0,
        "rejected": 0,
        "already_decided": 0,
    }
    assert data["cog_vintage"] == ref.cog_vintage
    assert data["postal_vintage"] == ref.postal_vintage


def test_reload(client: TestClient) -> None:
    response = client.post("/api/project/reload")
    assert response.status_code == 200
    assert response.json()["counts"]["total"] == 8


# --- clusters -----------------------------------------------------------------


def test_cluster_list_and_filter(client: TestClient) -> None:
    clusters = client.get("/api/clusters").json()
    assert clusters[0] == {
        "id": ROUBAIX,
        "label": "Roubaix",
        "state": "todo",
        "confidence": "high",
        "occurrences": 5,
        "parent_id": None,
        "provisional_name": None,
        "place_id": None,
        "writing_count": 5,
    }
    assert len(clusters) == 8
    assert client.get("/api/clusters", params={"state": "validated"}).json() == []
    assert len(client.get("/api/clusters", params={"state": "todo"}).json()) == 8
    bad = client.get("/api/clusters", params={"state": "nope"})
    assert bad.status_code == 422
    assert isinstance(bad.json()["detail"], str)


def test_cluster_detail(client: TestClient) -> None:
    data = detail(client, ROUBAIX)
    assert data["id"] == ROUBAIX
    assert data["proposal"]["commune"] == "Roubaix"
    assert data["proposal"]["insee_code"] == "59512"
    assert data["origins"] == {}
    assert writings_of(data) == [
        "59100 Roubaix",
        "59512",
        "ROUBAIX, Nord, France",
        "Roubaix",
        "roubaix, Nord-Pas-de-Calais",
    ]
    by_text = {w["text"]: w for w in data["writings"]}
    assert by_text["59100 Roubaix"]["hint"] == "code postal + nom"
    assert by_text["59512"]["hint"] == "code INSEE"
    assert by_text["59512"]["occurrences"] == 1
    assert by_text["Roubaix"]["decided"] is None
    assert {"kind": "postal_code", "value": "59100", "hint": "code postal"} in by_text[
        "59100 Roubaix"
    ]["elements"]
    assert data["complements"] == []


def test_cluster_detail_lists_complements(client: TestClient) -> None:
    data = detail(client, "insee:69123")
    assert data["complements"] == [{"text": "Atelier Rose", "occurrences": 1}]


def test_unknown_cluster_is_404(client: TestClient) -> None:
    response = client.get(cluster_url("insee:00000"))
    assert response.status_code == 404
    assert isinstance(response.json()["detail"], str)
    assert client.post(cluster_url("insee:00000", "reject")).status_code == 404


# --- Step 1: the main path --------------------------------------------------------


def test_validate_with_an_unchecked_writing_then_undo(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    checked = [w for w in writings_of(roubaix) if w != "59512"]
    response = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": roubaix["proposal"], "checked": checked},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["split"] is not None
    assert result["split"]["id"].startswith("split:")
    assert result["split"]["parent_id"] == f"place:{result['place_id']}"
    assert result["split"]["label"] == "59512"
    decisions = registry.decisions(writings_of(roubaix))
    assert set(decisions) == set(checked)
    assert {d.place_id for d in decisions.values()} == {result["place_id"]}
    place = registry.place(result["place_id"])
    assert place.fields["commune"] == "Roubaix"
    assert set(place.origins.values()) == {"rule"}

    undo = client.post("/api/undo")
    assert undo.status_code == 200
    assert undo.json() == {"action": "validate"}
    assert registry.decisions(writings_of(roubaix)) == {}
    assert detail(client, ROUBAIX)["writings"] == roubaix["writings"]
    assert all(
        not c["id"].startswith("split:") for c in client.get("/api/clusters").json()
    )
    empty = client.post("/api/undo")
    assert empty.status_code == 409
    assert isinstance(empty.json()["detail"], str)


def test_export_is_a_valid_zip(client: TestClient) -> None:
    response = client.get("/api/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="lieux_varies_atelier.zip"' in disposition
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.testzip() is None
    assert "lieux.csv" in archive.namelist()


# --- validate -----------------------------------------------------------------


def test_validate_all_changed_field_is_manual(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    fields = dict(roubaix["proposal"], commune="Roubaix-ville")
    result = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": fields, "checked": writings_of(roubaix)},
    ).json()
    assert result["split"] is None
    place = registry.place(result["place_id"])
    assert place.fields["commune"] == "Roubaix-ville"
    assert place.origins["commune"] == "manual"
    assert place.origins["insee_code"] == "rule"
    clusters = client.get("/api/clusters", params={"state": "validated"}).json()
    assert [c["id"] for c in clusters] == [f"place:{result['place_id']}"]
    assert clusters[0]["place_id"] == result["place_id"]
    counts = client.get("/api/project").json()["counts"]
    assert counts["validated"] == 1 and counts["todo"] == 7


def test_validate_again_keeps_the_place(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    first = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": roubaix["proposal"], "checked": writings_of(roubaix)},
    ).json()
    place_cluster = f"place:{first['place_id']}"
    data = detail(client, place_cluster)
    assert data["place_id"] == first["place_id"]
    assert data["origins"]["commune"] == "rule"
    again = client.post(
        cluster_url(place_cluster, "validate"),
        json={"fields": {"commune": "Roubaix"}, "checked": writings_of(data)},
    )
    assert again.status_code == 200
    assert again.json()["place_id"] == first["place_id"]
    assert len(registry.places()) == 1


def test_unchecked_writing_of_a_validated_place_is_detached(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    first = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": roubaix["proposal"], "checked": writings_of(roubaix)},
    ).json()
    place_cluster = f"place:{first['place_id']}"
    checked = [w for w in writings_of(roubaix) if w != "59512"]
    result = client.post(
        cluster_url(place_cluster, "validate"),
        json={"fields": roubaix["proposal"], "checked": checked},
    ).json()
    assert result["split"]["writing_count"] == 1
    assert registry.decision("59512") is None
    split = detail(client, result["split"]["id"])
    assert split["state"] == "todo"
    assert client.post("/api/undo").json() == {"action": "validate"}
    assert registry.decision("59512") is not None
    assert writings_of(detail(client, place_cluster)) == writings_of(roubaix)


@pytest.mark.parametrize(
    "checked",
    [[], ["Lille"], ["Nulle Part"]],
)
def test_validate_rejects_bad_checked(client: TestClient, checked: list[str]) -> None:
    response = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": {"commune": "Roubaix"}, "checked": checked},
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_validate_rejects_bad_fields(client: TestClient) -> None:
    unknown = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": {"planet": "Mars"}, "checked": ["Roubaix"]},
    )
    assert unknown.status_code == 422
    empty = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": {"commune": "  "}, "checked": ["Roubaix"]},
    )
    assert empty.status_code == 400


# --- split / reject / correct -----------------------------------------------------


def test_split_then_undo(client: TestClient) -> None:
    response = client.post(cluster_url(ROUBAIX, "split"), json={"writings": ["59512"]})
    assert response.status_code == 200
    new = response.json()
    assert new["parent_id"] == ROUBAIX
    assert new["provisional_name"] == "59512"
    assert writings_of(detail(client, new["id"])) == ["59512"]
    assert client.post("/api/undo").json() == {"action": "split"}
    assert client.get(cluster_url(new["id"])).status_code == 404


def test_split_rejects_every_writing(client: TestClient) -> None:
    writings = writings_of(detail(client, ROUBAIX))
    response = client.post(cluster_url(ROUBAIX, "split"), json={"writings": writings})
    assert response.status_code == 400


def test_reject_then_undo(client: TestClient, registry: PlaceRegistry) -> None:
    response = client.post(cluster_url("name:en mer", "reject"))
    assert response.status_code == 200
    assert response.json() == {"writings": ["En mer"]}
    decision = registry.decision("En mer")
    assert decision is not None and decision.status == "rejected"
    assert client.get("/api/project").json()["counts"]["rejected"] == 1
    assert client.post("/api/undo").json() == {"action": "reject"}
    assert registry.decision("En mer") is None


def test_correct_a_place_then_undo(client: TestClient, registry: PlaceRegistry) -> None:
    lyon = detail(client, "insee:69123")
    place_id = client.post(
        cluster_url("insee:69123", "validate"),
        json={"fields": lyon["proposal"], "checked": writings_of(lyon)},
    ).json()["place_id"]
    response = client.patch(
        f"/api/places/{place_id}", json={"field": "former_name", "value": "Lugdunum"}
    )
    assert response.status_code == 200
    assert response.json()["fields"]["former_name"] == "Lugdunum"
    assert response.json()["origins"]["former_name"] == "manual"
    assert client.post("/api/undo").json() == {"action": "correct"}
    assert "former_name" not in registry.place(place_id).fields
    assert (
        client.patch(
            "/api/places/absent", json={"field": "commune", "value": "X"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/places/{place_id}", json={"field": "planet", "value": "X"}
        ).status_code
        == 422
    )


def test_undo_conflict_is_409(client: TestClient, registry: PlaceRegistry) -> None:
    client.post(cluster_url("name:en mer", "reject"))
    # Another session decides the same writing: the undo would overwrite it.
    registry.validate(["En mer"], {"commune": "Mer"}, {"commune": "manual"}, "other")
    response = client.post("/api/undo")
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)


# --- occurrences ------------------------------------------------------------------


def test_occurrences(client: TestClient) -> None:
    response = client.post("/api/occurrences", json={"writing": "Lyon"})
    assert response.status_code == 200
    occurrences = response.json()
    assert {
        "subject": "person",
        "label": "Jean DUPONT",
        "kind": "resi",
        "kind_label": "Résidence",
        "date": "1870",
        "complement": None,
    } in occurrences
    assert client.post("/api/occurrences", json={"writing": "Nulle"}).status_code == 404


def test_occurrences_of_a_family(client: TestClient) -> None:
    occurrences = client.post("/api/occurrences", json={"writing": "Roubaix"}).json()
    marriage = [o for o in occurrences if o["kind"] == "marriage"]
    assert marriage == [
        {
            "subject": "family",
            "label": "Jean DUPONT × Marie MARTIN",
            "kind": "marriage",
            "kind_label": "Mariage",
            "date": "1875",
            "complement": None,
        }
    ]


# --- Step 2 (Review Focus 2): a writing full of URL-hostile characters ----------


def test_special_writing_round_trips(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData
) -> None:
    client = make_client(tmp_path, registry, ref, "ecriture_speciale.gw")
    response = client.post("/api/occurrences", json={"writing": SPECIAL})
    assert response.status_code == 200
    assert [o["kind"] for o in response.json()] == ["marriage"]
    (cluster,) = [
        c for c in client.get("/api/clusters").json() if c["label"].startswith("Paris")
    ]
    data = detail(client, cluster["id"])
    assert writings_of(data) == [SPECIAL]
    result = client.post(
        cluster_url(cluster["id"], "validate"),
        json={"fields": {"commune": "Paris"}, "checked": [SPECIAL]},
    )
    assert result.status_code == 200
    decision = registry.decision(SPECIAL)
    assert decision is not None and decision.place_id == result.json()["place_id"]


# --- Step 3 (Review Focus 1): a base without any place ------------------------------


def test_base_without_places(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData
) -> None:
    client = make_client(tmp_path, registry, ref, "sans_lieux.gw")
    assert client.get("/api/project").json()["counts"]["total"] == 0
    assert client.get("/api/clusters").json() == []
    response = client.get("/api/export")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    lines = archive.read("lieux.csv").decode("utf-8").strip().splitlines()
    assert len(lines) == 1  # header only


# --- registry export / import -------------------------------------------------------


def test_registry_export(client: TestClient, registry: PlaceRegistry) -> None:
    registry.reject(["En mer"], "p")
    response = client.get("/api/registry/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert (
        'filename="referentiel_lieux.json"' in response.headers["content-disposition"]
    )
    data = response.json()
    assert data["format"] == "prosopo-gw-atelier/lieux"
    assert [w["writing"] for w in data["writings"]] == ["En mer"]


def other_registry_document(tmp_path: Path) -> dict[str, Any]:
    with PlaceRegistry(tmp_path / "other.sqlite") as other:
        other.validate(
            ["En mer", "Lyon"], {"commune": "Mer"}, {"commune": "manual"}, "other"
        )
        return export_registry(other)


def upload(client: TestClient, content: bytes) -> Any:
    return client.post(
        "/api/registry/import",
        files={"file": ("referentiel_lieux.json", content, "application/json")},
    )


def test_import_with_conflict_then_resolve_and_undo(
    tmp_path: Path, client: TestClient, registry: PlaceRegistry
) -> None:
    registry.reject(["En mer"], "p")
    document = other_registry_document(tmp_path)
    response = upload(client, json.dumps(document).encode("utf-8"))
    assert response.status_code == 200, response.text
    incoming_place = document["places"][0]["place_id"]
    conflict = {
        "writing": "En mer",
        "current": {"status": "rejected", "place_id": None, "place_label": None},
        "incoming": {
            "status": "validated",
            "place_id": incoming_place,
            "place_label": "Mer",
        },
    }
    assert response.json() == {"conflicts": [conflict]}
    lyon = registry.decision("Lyon")
    assert lyon is not None and lyon.place_id == incoming_place
    assert client.get("/api/registry/conflicts").json() == {"conflicts": [conflict]}

    missing = client.post(
        "/api/registry/conflicts/resolve", json={"writing": "Lyon", "keep": "incoming"}
    )
    assert missing.status_code == 404
    resolved = client.post(
        "/api/registry/conflicts/resolve",
        json={"writing": "En mer", "keep": "incoming"},
    )
    assert resolved.status_code == 200
    assert resolved.json() == {"conflicts": []}
    en_mer = registry.decision("En mer")
    assert en_mer is not None and en_mer.place_id == incoming_place

    assert client.post("/api/undo").json() == {"action": "resolve"}
    en_mer = registry.decision("En mer")
    assert en_mer is not None and en_mer.status == "rejected"
    assert client.post("/api/undo").json() == {"action": "import"}
    assert registry.decision("Lyon") is None


def test_resolve_keep_current(
    tmp_path: Path, client: TestClient, registry: PlaceRegistry
) -> None:
    registry.reject(["En mer"], "p")
    upload(client, json.dumps(other_registry_document(tmp_path)).encode("utf-8"))
    response = client.post(
        "/api/registry/conflicts/resolve",
        json={"writing": "En mer", "keep": "current"},
    )
    assert response.json() == {"conflicts": []}
    decision = registry.decision("En mer")
    assert decision is not None and decision.status == "rejected"


def test_resolve_stale_conflict_is_409(
    tmp_path: Path, client: TestClient, registry: PlaceRegistry
) -> None:
    registry.reject(["En mer"], "p")
    upload(client, json.dumps(other_registry_document(tmp_path)).encode("utf-8"))
    registry.detach(["En mer"], "p")
    response = client.post(
        "/api/registry/conflicts/resolve",
        json={"writing": "En mer", "keep": "incoming"},
    )
    assert response.status_code == 409
    assert client.get("/api/registry/conflicts").json() == {"conflicts": []}


@pytest.mark.parametrize(
    "content", [b"{not json", b"\xff\xfe", b'{"format": "autre"}', b"[]"]
)
def test_import_rejects_invalid_documents(client: TestClient, content: bytes) -> None:
    response = upload(client, content)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_import_rejects_too_large_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_app, "MAX_IMPORT_BYTES", 10)
    response = upload(client, b'{"format": "prosopo-gw-atelier/lieux"}')
    assert response.status_code == 413


# --- Step 4: security ---------------------------------------------------------------


def test_foreign_host_is_rejected(client: TestClient) -> None:
    response = client.get("/api/project", headers={"Host": "evil.example"})
    assert response.status_code == 400


def test_localhost_is_accepted(client: TestClient) -> None:
    response = client.get("/api/project", headers={"Host": "localhost:8765"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "null", "http://127.0.0.1.evil.example:80"]
)
def test_foreign_origin_cannot_change_state(client: TestClient, origin: str) -> None:
    response = client.post(
        cluster_url("name:en mer", "reject"), headers={"Origin": origin}
    )
    assert response.status_code == 403
    assert client.get("/api/project").json()["counts"]["rejected"] == 0
    patch = client.patch(
        "/api/places/x",
        json={"field": "commune", "value": "X"},
        headers={"Origin": origin},
    )
    assert patch.status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8765", "http://localhost:51234"])
def test_local_origin_can_change_state(client: TestClient, origin: str) -> None:
    response = client.post(
        cluster_url("name:en mer", "reject"), headers={"Origin": origin}
    )
    assert response.status_code == 200


def test_index_and_static(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Atelier" in response.text
    assert client.get("/static/absent.js").status_code == 404


# --- fix round 1: blanked fields, partial undo ----------------------------------------


def validated_roubaix(client: TestClient) -> tuple[str, dict[str, Any]]:
    roubaix = detail(client, ROUBAIX)
    assert roubaix["proposal"]["department"] == "59"
    place_id = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": roubaix["proposal"], "checked": writings_of(roubaix)},
    ).json()["place_id"]
    return place_id, roubaix


def test_validate_with_a_blank_field_removes_it_then_undo(
    client: TestClient, registry: PlaceRegistry
) -> None:
    place_id, roubaix = validated_roubaix(client)
    place_cluster = f"place:{place_id}"
    fields = {**roubaix["proposal"], "department": "  "}
    response = client.post(
        cluster_url(place_cluster, "validate"),
        json={"fields": fields, "checked": writings_of(roubaix)},
    )
    assert response.status_code == 200, response.text
    place = registry.place(place_id)
    assert "department" not in place.fields
    assert "department" not in place.origins
    assert "department" not in detail(client, place_cluster)["origins"]
    assert client.post("/api/undo").json() == {"action": "validate"}
    place = registry.place(place_id)
    assert place.fields["department"] == "59"
    assert place.origins["department"] == "rule"


def test_patch_with_an_empty_value_removes_the_field_then_undo(
    client: TestClient, registry: PlaceRegistry
) -> None:
    place_id, _ = validated_roubaix(client)
    response = client.patch(
        f"/api/places/{place_id}", json={"field": "department", "value": " "}
    )
    assert response.status_code == 200
    assert "department" not in response.json()["fields"]
    assert "department" not in response.json()["origins"]
    assert client.post("/api/undo").json() == {"action": "correct"}
    assert registry.place(place_id).fields["department"] == "59"


def test_partial_undo_keeps_the_rest_of_the_action(
    client: TestClient, registry: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    roubaix = detail(client, ROUBAIX)
    checked = [w for w in writings_of(roubaix) if w != "59512"]
    result = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"fields": roubaix["proposal"], "checked": checked},
    ).json()
    split_id = result["split"]["id"]
    project = client.app.state.atelier.project  # type: ignore[attr-defined]

    def broken(split: str) -> None:
        raise KeyError(split)

    monkeypatch.setattr(project, "unsplit", broken)
    response = client.post("/api/undo")
    assert response.status_code == 409
    assert "partiellement" in response.json()["detail"]
    # The registry part was undone; the split is still there.
    assert registry.decision("Roubaix") is None
    assert detail(client, split_id)["writings"]
    # The rest of the action stays on the stack: a retry finishes it.
    monkeypatch.undo()
    assert client.post("/api/undo").json() == {"action": "validate"}
    assert client.get(cluster_url(split_id)).status_code == 404
    assert client.post("/api/undo").status_code == 409
