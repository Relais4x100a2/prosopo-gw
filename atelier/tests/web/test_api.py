import dataclasses
import io
import json
import shutil
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from prosopo_gw_atelier.places.levels import (
    FOREIGN_TYPES,
    FRENCH_TYPES,
    TYPE_LABELS,
    Level,
)
from prosopo_gw_atelier.project import Project
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store.exchange import export_registry
from prosopo_gw_atelier.store.registry import PlaceRegistry
from prosopo_gw_atelier.web import app as web_app
from prosopo_gw_atelier.web.app import create_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROUBAIX = "insee:59512"
SPECIAL = 'Paris / Seine ? #1 "bis"'
MER = (Level(0, "Mer", type="commune", origin="manual"),)

HESDIN_GW = """encoding: utf-8
gwplus

fam DURAND Paul 1850 #bp Marconne,_Pas-de-Calais + LEFEBVRE Jeanne 1852
beg
- h Jacques 1876 #bp Hesdin-la-Forêt
end
"""

UNKNOWN_CODE_GW = """encoding: utf-8
gwplus

pevt DUPONT Jean
#buri 1910 #p 99999
end pevt
"""


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


def gw_client(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData, text: str
) -> TestClient:
    """A client on a synthetic base given as text."""
    gw = tmp_path / "bases" / "synthetique.gw"
    gw.parent.mkdir(parents=True, exist_ok=True)
    gw.write_text(text, encoding="utf-8")
    project = Project.open(gw, registry, ref, tmp_path / "data" / "projets")
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


def validate_body(
    data: dict[str, Any], checked: list[str] | None = None
) -> dict[str, Any]:
    """The body that validates a cluster's detail as shown."""
    return {
        "levels": data["levels"],
        "postal_code": data["postal_code"],
        "checked": writings_of(data) if checked is None else checked,
    }


def level_out(level: Level) -> dict[str, Any]:
    return dataclasses.asdict(level)


AT = "'2026-01-01T00:00:00+00:00'"


def v1_registry(path: Path) -> None:
    """A synthetic v1 registry: Lille with former name Lomme."""
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / "registry_v1.sql").read_text("utf-8"))
    conn.executescript(f"""
      INSERT INTO places VALUES ('p-lille', {AT});
      INSERT INTO place_fields VALUES
        ('p-lille','commune','Lille','reference'),
        ('p-lille','insee_code','59350','reference'),
        ('p-lille','department','59','reference'),
        ('p-lille','region','Hauts-de-France','reference'),
        ('p-lille','country','France','rule'),
        ('p-lille','former_name','Lomme','rule'),
        ('p-lille','postal_code','59000','rule');
      INSERT INTO writings VALUES
        ('Lille', 'p-lille', 'validated', 'p1', {AT}),
        ('Lomme', 'p-lille', 'validated', 'p1', {AT});
    """)
    conn.close()


# --- project ------------------------------------------------------------------


def test_project_summary(client: TestClient, ref: RefData) -> None:
    response = client.get("/api/project")
    assert response.status_code == 200
    data = response.json()
    assert data["gw_name"] == "lieux_varies.gw"
    assert data["gw_changed"] is False
    # Lomme, a former commune of Lille, is a cluster of its own.
    assert data["counts"] == {
        "total": 9,
        "todo": 9,
        "validated": 0,
        "rejected": 0,
        "already_decided": 0,
    }
    assert data["cog_vintage"] == ref.cog_vintage
    assert data["postal_vintage"] == ref.postal_vintage


def test_project_lists_level_types(client: TestClient) -> None:
    types = client.get("/api/project").json()["level_types"]
    values = [t["value"] for t in types]
    assert values == [*FRENCH_TYPES, *FOREIGN_TYPES]
    assert {"value": "commune_historique", "label": "Commune historique"} in types
    assert {"value": "comte", "label": "Comté"} in types
    assert all(t["label"] == TYPE_LABELS[t["value"]] for t in types)


def test_reload(client: TestClient) -> None:
    response = client.post("/api/project/reload")
    assert response.status_code == 200
    assert response.json()["counts"]["total"] == 9


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
    assert len(clusters) == 9
    assert client.get("/api/clusters", params={"state": "validated"}).json() == []
    assert len(client.get("/api/clusters", params={"state": "todo"}).json()) == 9
    bad = client.get("/api/clusters", params={"state": "nope"})
    assert bad.status_code == 422
    assert isinstance(bad.json()["detail"], str)


def test_cluster_detail(client: TestClient) -> None:
    data = detail(client, ROUBAIX)
    assert data["id"] == ROUBAIX
    assert [(lv["rank"], lv["name"], lv["type"]) for lv in data["levels"]] == [
        (0, "Roubaix", "commune"),
        (1, "Nord", "departement"),
        (2, "Nord-Pas-de-Calais", "ancienne_region"),
        (3, "Hauts-de-France", "region"),
        (4, "France", "pays"),
    ]
    assert data["levels"][0]["identifier"] == "59512"
    assert data["levels"][0]["origin"] == "insee"
    assert data["levels"][0]["status"] == "validated"
    # A level the reference does not know keeps the writing as its origin.
    assert data["levels"][2]["origin"] == "written"
    assert data["postal_code"] == "59100"
    assert data["view"]["commune"] == "Roubaix"
    assert data["view"]["insee_code"] == "59512"
    assert data["view"]["postal_code"] == "59100"
    assert data["view_origins"]["commune"] == "insee"
    assert "postal_code" not in data["view_origins"]
    assert data["from_registry"] is False
    assert data["needs_manual_levels"] is False
    assert data["alternatives"] == []
    assert data["historical_writings"] == {}
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


def test_detail_has_levels_and_view(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData
) -> None:
    client = gw_client(tmp_path, registry, ref, HESDIN_GW)
    data = detail(client, "historique:62549|marconne")
    assert data["label"] == "Marconne"
    assert data["levels"][0]["type"] == "commune_historique"
    assert data["levels"][0]["name"] == "Marconne"
    assert data["levels"][0]["identifier"] == "62549"
    assert data["levels"][0]["nature"] == "deleguee"
    assert data["levels"][1]["type"] == "commune"
    assert data["view"]["commune"] == "Hesdin-la-Forêt"
    assert data["view"]["historical_commune"] == "Marconne"
    assert data["view_origins"]["historical_commune"] == "insee"
    assert data["from_registry"] is False


def test_detail_of_a_cluster_to_enter_by_hand(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData
) -> None:
    client = gw_client(tmp_path, registry, ref, UNKNOWN_CODE_GW)
    data = detail(client, "name:99999")
    assert data["levels"] == []
    assert data["view"] == {}
    assert data["needs_manual_levels"] is True
    response = client.post(
        cluster_url("name:99999", "validate"),
        json={"levels": [], "postal_code": None, "checked": ["99999"]},
    )
    assert response.status_code == 400
    assert registry.decisions(["99999"]) == {}


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
        cluster_url(ROUBAIX, "validate"), json=validate_body(roubaix, checked)
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
    assert [level_out(lv) for lv in place.levels] == roubaix["levels"]

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


def test_validate_with_levels_keeps_rule_origins(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    # Sent back as shown: every level keeps its rule origin.
    result = client.post(
        cluster_url(ROUBAIX, "validate"), json=validate_body(roubaix)
    ).json()
    place = registry.place(result["place_id"])
    origins = ["insee", "insee", "written", "insee", "insee"]
    assert [lv.origin for lv in place.levels] == origins
    assert (place.postal_code, place.postal_origin) == ("59100", "written")
    assert client.post("/api/undo").json() == {"action": "validate"}

    # A renamed level, and a changed postal code, become manual; the client's
    # origins are not trusted.
    levels = [dict(lv) for lv in roubaix["levels"]]
    levels[0]["name"] = "Roubaix-ville"
    levels[1]["origin"] = "manual"
    levels[2]["origin"] = "geonames"
    body = {"levels": levels, "postal_code": "59101", "checked": writings_of(roubaix)}
    result = client.post(cluster_url(ROUBAIX, "validate"), json=body).json()
    assert result["split"] is None
    place = registry.place(result["place_id"])
    assert place.fields["commune"] == "Roubaix-ville"
    assert [lv.origin for lv in place.levels] == ["manual", *origins[1:]]
    assert (place.postal_code, place.postal_origin) == ("59101", "manual")
    clusters = client.get("/api/clusters", params={"state": "validated"}).json()
    assert [c["id"] for c in clusters] == [f"place:{result['place_id']}"]
    assert clusters[0]["place_id"] == result["place_id"]
    counts = client.get("/api/project").json()["counts"]
    assert counts["validated"] == 1 and counts["todo"] == 8


def test_validate_renumbers_the_levels(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    levels = [dict(lv, rank=9) for lv in roubaix["levels"]]
    levels.insert(0, {"rank": 0, "name": " Le Hameau ", "type": "lieu_dit"})
    body = {"levels": levels, "postal_code": None, "checked": writings_of(roubaix)}
    response = client.post(cluster_url(ROUBAIX, "validate"), json=body)
    assert response.status_code == 200, response.text
    place = registry.place(response.json()["place_id"])
    assert [(lv.rank, lv.name) for lv in place.levels][:2] == [
        (0, "Le Hameau"),
        (1, "Roubaix"),
    ]
    assert place.levels[0].origin == "manual"
    assert (place.postal_code, place.postal_origin) == (None, None)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("empty", "au moins un niveau"),
        ("blank_name", "nom du niveau 1 est vide"),
        ("bad_type", "type du niveau 1 est invalide"),
        ("bad_latitude", "latitude du niveau 1"),
    ],
)
def test_validate_rejects_bad_levels(
    client: TestClient, registry: PlaceRegistry, change: str, message: str
) -> None:
    roubaix = detail(client, ROUBAIX)
    levels = [dict(lv) for lv in roubaix["levels"]]
    if change == "empty":
        levels = []
    elif change == "blank_name":
        levels[0]["name"] = "  "
    elif change == "bad_type":
        levels[0]["type"] = "Comté"
    else:
        levels[0]["latitude"] = 200
    body = {"levels": levels, "postal_code": None, "checked": writings_of(roubaix)}
    response = client.post(cluster_url(ROUBAIX, "validate"), json=body)
    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert registry.decisions(writings_of(roubaix)) == {}
    assert client.post("/api/undo").status_code == 409


def test_validate_needs_a_validated_level(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    levels = [dict(lv, status="proposed") for lv in roubaix["levels"]]
    body = {"levels": levels, "postal_code": None, "checked": writings_of(roubaix)}
    response = client.post(cluster_url(ROUBAIX, "validate"), json=body)
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "La chaîne doit contenir au moins un niveau validé."
    )
    assert registry.decisions(writings_of(roubaix)) == {}


def test_validate_rejects_bad_level_values(client: TestClient) -> None:
    roubaix = detail(client, ROUBAIX)
    for change in ({"nature": "martienne"}, {"status": "peut-etre"}, {"name": None}):
        levels = [dict(roubaix["levels"][0], **change)]
        response = client.post(
            cluster_url(ROUBAIX, "validate"),
            json={"levels": levels, "postal_code": None, "checked": ["Roubaix"]},
        )
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)


def test_validate_again_keeps_the_place(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    first = client.post(
        cluster_url(ROUBAIX, "validate"), json=validate_body(roubaix)
    ).json()
    place_cluster = f"place:{first['place_id']}"
    data = detail(client, place_cluster)
    assert data["place_id"] == first["place_id"]
    assert data["from_registry"] is True
    assert data["view_origins"]["commune"] == "insee"
    body = {
        "levels": [{"rank": 0, "name": "Roubaix", "type": "commune"}],
        "postal_code": None,
        "checked": writings_of(data),
    }
    again = client.post(cluster_url(place_cluster, "validate"), json=body)
    assert again.status_code == 200
    assert again.json()["place_id"] == first["place_id"]
    assert len(registry.places()) == 1
    # The chain sent replaces the place's.
    assert [lv.name for lv in registry.place(first["place_id"]).levels] == ["Roubaix"]


def test_validating_an_anchored_cluster_keeps_its_manual_level(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData
) -> None:
    stored = (
        Level(0, "Roubaix", type="commune", identifier="59512", origin="manual"),
        Level(1, "Ferrain", origin="manual"),
    )
    place_id = registry.validate(
        ["Roubaix-Ville"], stored, "59101", "manual", "other"
    ).place_id
    client = make_client(tmp_path, registry, ref, "lieux_varies.gw")
    data = detail(client, ROUBAIX)
    assert data["place_id"] == place_id
    assert data["from_registry"] is True
    assert data["levels"][1]["name"] == "Ferrain"
    assert data["postal_code"] == "59101"
    response = client.post(cluster_url(ROUBAIX, "validate"), json=validate_body(data))
    assert response.status_code == 200, response.text
    assert response.json()["place_id"] == place_id
    place = registry.place(place_id)
    assert place.levels == stored
    assert place.levels[0].origin == "manual"
    assert (place.postal_code, place.postal_origin) == ("59101", "manual")
    assert len(registry.places()) == 1


def test_unchecked_writing_of_a_validated_place_is_detached(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    first = client.post(
        cluster_url(ROUBAIX, "validate"), json=validate_body(roubaix)
    ).json()
    place_cluster = f"place:{first['place_id']}"
    checked = [w for w in writings_of(roubaix) if w != "59512"]
    result = client.post(
        cluster_url(place_cluster, "validate"),
        json=validate_body(detail(client, place_cluster), checked),
    ).json()
    assert result["split"]["writing_count"] == 1
    assert registry.decision("59512") is None
    split = detail(client, result["split"]["id"])
    assert split["state"] == "todo"
    assert client.post("/api/undo").json() == {"action": "validate"}
    assert registry.decision("59512") is not None
    assert writings_of(detail(client, place_cluster)) == writings_of(roubaix)


WATTRELOS = {"rank": 0, "name": "Wattrelos", "type": "commune"}


def test_validating_a_split_of_a_place_does_not_touch_that_place(
    client: TestClient, registry: PlaceRegistry
) -> None:
    roubaix = detail(client, ROUBAIX)
    checked = [w for w in writings_of(roubaix) if w != "59512"]
    first = client.post(
        cluster_url(ROUBAIX, "validate"), json=validate_body(roubaix, checked)
    ).json()
    parent = first["place_id"]
    before = registry.place(parent)
    split_id = first["split"]["id"]
    # The user took it out on purpose: no anchor on the place it left.
    assert first["split"]["place_id"] is None
    assert detail(client, split_id)["place_id"] is None

    result = client.post(
        cluster_url(split_id, "validate"),
        json={"levels": [WATTRELOS], "postal_code": None, "checked": ["59512"]},
    )
    assert result.status_code == 200, result.text
    new_place = result.json()["place_id"]
    assert new_place != parent
    assert registry.place(parent) == before
    split = detail(client, split_id)
    assert split["state"] == "validated"
    assert split["place_id"] == new_place
    assert split["view"] == {"commune": "Wattrelos"}
    assert split["view_origins"] == {"commune": "manual"}


def test_validating_a_split_twice_keeps_one_place(
    client: TestClient, registry: PlaceRegistry
) -> None:
    lille = detail(client, "insee:59350")
    split = client.post(
        cluster_url("insee:59350", "split"), json={"writings": ["Lille"]}
    ).json()
    assert split["place_id"] is None
    places = []
    for commune in ("Lille", "Lille-en-Flandre"):
        level = {"rank": 0, "name": commune, "type": "commune"}
        response = client.post(
            cluster_url(split["id"], "validate"),
            json={"levels": [level], "postal_code": None, "checked": ["Lille"]},
        )
        assert response.status_code == 200, response.text
        places.append(response.json()["place_id"])
        data = detail(client, split["id"])
        assert data["state"] == "validated"
        assert data["place_id"] == places[0]
        assert data["view"] == {"commune": commune}
        assert data["view_origins"] == {"commune": "manual"}
    assert places[0] == places[1]
    assert len(registry.places()) == 1
    assert "Lille" not in writings_of(detail(client, "insee:59350"))
    assert len(writings_of(lille)) == 3


@pytest.mark.parametrize(
    "checked",
    [[], ["Lille"], ["Nulle Part"]],
)
def test_validate_rejects_bad_checked(client: TestClient, checked: list[str]) -> None:
    response = client.post(
        cluster_url(ROUBAIX, "validate"),
        json={"levels": [WATTRELOS], "postal_code": None, "checked": checked},
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


# --- split / reject / places ------------------------------------------------------


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


def test_reject_keeps_the_cluster_whole(client: TestClient) -> None:
    lille = writings_of(detail(client, "insee:59350"))
    assert client.post(cluster_url("insee:59350", "reject")).status_code == 200
    clusters = client.get("/api/clusters").json()
    assert len(clusters) == 9
    rejected = [c for c in clusters if c["state"] == "rejected"]
    assert [c["id"] for c in rejected] == ["rejected:insee:59350"]
    data = detail(client, "rejected:insee:59350")
    assert writings_of(data) == lille
    assert data["levels"] == [] and data["needs_manual_levels"] is False
    assert client.get("/api/project").json()["counts"]["rejected"] == 1
    assert client.post("/api/undo").json() == {"action": "reject"}
    assert "insee:59350" in {c["id"] for c in client.get("/api/clusters").json()}


def test_put_levels_and_undo(client: TestClient, registry: PlaceRegistry) -> None:
    lyon = detail(client, "insee:69123")
    place_id = client.post(
        cluster_url("insee:69123", "validate"), json=validate_body(lyon)
    ).json()["place_id"]
    before = registry.place(place_id)
    levels = [{"rank": 0, "name": "Croix-Rousse", "type": "quartier"}, *lyon["levels"]]
    response = client.put(
        f"/api/places/{place_id}/levels",
        json={"levels": levels, "postal_code": "69004"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["place_id"] == place_id
    assert [(lv["rank"], lv["name"]) for lv in data["levels"]][:2] == [
        (0, "Croix-Rousse"),
        (1, "Lyon"),
    ]
    # Only the new level is manual; the others keep the place's origins.
    assert [lv["origin"] for lv in data["levels"]] == [
        "manual",
        *(lv["origin"] for lv in lyon["levels"]),
    ]
    assert data["postal_code"] == "69004"
    assert data["view"]["commune"] == "Lyon"
    assert data["view"]["postal_code"] == "69004"
    assert registry.place(place_id).postal_origin == "manual"
    assert client.post("/api/undo").json() == {"action": "correct"}
    assert registry.place(place_id) == before


def test_put_levels_errors(client: TestClient, registry: PlaceRegistry) -> None:
    place_id, roubaix = validated_roubaix(client)
    before = registry.place(place_id)
    absent = client.put(
        "/api/places/absent/levels", json={"levels": [WATTRELOS], "postal_code": None}
    )
    assert absent.status_code == 404
    assert isinstance(absent.json()["detail"], str)
    empty = client.put(
        f"/api/places/{place_id}/levels", json={"levels": [], "postal_code": None}
    )
    assert empty.status_code == 400
    assert "au moins un niveau" in empty.json()["detail"]
    bad = client.put(
        f"/api/places/{place_id}/levels",
        json={"levels": [dict(WATTRELOS, type="Comté")], "postal_code": None},
    )
    assert bad.status_code == 400
    invalid = client.put(f"/api/places/{place_id}/levels", json={"levels": "x"})
    assert invalid.status_code == 422
    assert registry.place(place_id) == before
    # The old field-by-field route is gone.
    old = client.patch(f"/api/places/{place_id}", json={"field": "commune"})
    assert old.status_code == 404


def test_put_levels_needs_a_validated_level(
    client: TestClient, registry: PlaceRegistry
) -> None:
    place_id, roubaix = validated_roubaix(client)
    before = registry.place(place_id)
    levels = [dict(lv, status="proposed") for lv in roubaix["levels"]]
    response = client.put(
        f"/api/places/{place_id}/levels",
        json={"levels": levels, "postal_code": roubaix["postal_code"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "La chaîne doit contenir au moins un niveau validé."
    )
    assert registry.place(place_id) == before


def test_noop_put_levels_pushes_no_undo_entry(
    client: TestClient, registry: PlaceRegistry
) -> None:
    place_id, roubaix = validated_roubaix(client)
    journal = registry.journal()
    response = client.put(
        f"/api/places/{place_id}/levels",
        json={"levels": roubaix["levels"], "postal_code": roubaix["postal_code"]},
    )
    assert response.status_code == 200, response.text
    assert registry.journal() == journal
    # The only undoable action is still the validation.
    assert client.post("/api/undo").json() == {"action": "validate"}
    assert client.post("/api/undo").status_code == 409


@pytest.mark.parametrize("action", ["accept", "refuse"])
def test_proposal_race_is_a_french_409(
    tmp_path: Path, ref: RefData, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    path = tmp_path / "data" / "referentiel.sqlite"
    path.parent.mkdir(parents=True)
    v1_registry(path)
    with PlaceRegistry(path, ref) as registry:
        client = make_client(tmp_path, registry, ref, "lieux_varies.gw")

        def raced(*args: object) -> None:
            raise ValueError("place p-lille has no proposed level at rank 0")

        monkeypatch.setattr(registry, f"{action}_proposal", raced)
        response = client.post(f"/api/places/p-lille/levels/0/{action}")
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Ce niveau n'est plus une proposition : il a changé entre-temps ; "
            "rechargez le lieu."
        )


def test_put_levels_removing_a_level_then_undo(
    client: TestClient, registry: PlaceRegistry
) -> None:
    place_id, roubaix = validated_roubaix(client)
    levels = [lv for lv in roubaix["levels"] if lv["type"] != "departement"]
    response = client.put(
        f"/api/places/{place_id}/levels",
        json={"levels": levels, "postal_code": roubaix["postal_code"]},
    )
    assert response.status_code == 200
    assert "department" not in response.json()["view"]
    assert "department" not in registry.place(place_id).fields
    assert registry.place(place_id).postal_origin == "written"
    assert client.post("/api/undo").json() == {"action": "correct"}
    assert registry.place(place_id).fields["department"] == "59"


def test_accept_and_refuse_proposal_routes(tmp_path: Path, ref: RefData) -> None:
    path = tmp_path / "data" / "referentiel.sqlite"
    path.parent.mkdir(parents=True)
    v1_registry(path)
    with PlaceRegistry(path, ref) as registry:
        client = make_client(tmp_path, registry, ref, "lieux_varies.gw")
        data = detail(client, "place:p-lille")
        assert [(lv["name"], lv["status"]) for lv in data["levels"]][:2] == [
            ("Lomme", "proposed"),
            ("Lille", "validated"),
        ]
        # A proposed level is not in the view.
        assert "historical_commune" not in data["view"]
        before = registry.place("p-lille")

        accepted = client.post("/api/places/p-lille/levels/0/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["levels"][0]["status"] == "validated"
        assert accepted.json()["view"]["historical_commune"] == "Lomme"
        assert client.post("/api/undo").json() == {"action": "correct"}
        assert registry.place("p-lille") == before

        refused = client.post("/api/places/p-lille/levels/0/refuse")
        assert refused.status_code == 200, refused.text
        assert refused.json()["levels"][0]["name"] == "Lille"
        assert len(refused.json()["levels"]) == len(before.levels) - 1
        assert client.post("/api/undo").json() == {"action": "correct"}
        assert registry.place("p-lille") == before

        for url, status in [
            ("/api/places/absent/levels/0/accept", 404),
            ("/api/places/p-lille/levels/9/accept", 404),
            ("/api/places/p-lille/levels/9/refuse", 404),
            ("/api/places/p-lille/levels/1/accept", 409),
            ("/api/places/p-lille/levels/1/refuse", 409),
        ]:
            response = client.post(url)
            assert response.status_code == status, url
            assert isinstance(response.json()["detail"], str)
        assert registry.place("p-lille") == before
        assert client.post("/api/undo").status_code == 409


def test_refusing_the_only_level_is_a_clear_409(
    client: TestClient, registry: PlaceRegistry
) -> None:
    place_id, _ = validated_roubaix(client)
    only = Level(rank=0, name="Roubaix", origin="written", status="proposed")
    registry.set_levels(place_id, [only], None, None, "p1")
    before = registry.place(place_id)
    response = client.post(f"/api/places/{place_id}/levels/0/refuse")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Ce niveau est le seul du lieu : ajoutez-en un autre avant de le refuser."
    )
    assert registry.place(place_id) == before


def test_undo_conflict_is_409(client: TestClient, registry: PlaceRegistry) -> None:
    client.post(cluster_url("name:en mer", "reject"))
    # Another session decides the same writing: the undo would overwrite it.
    registry.validate(["En mer"], MER, None, None, "other")
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
        json={
            "levels": [{"rank": 0, "name": "Paris", "type": "commune"}],
            "postal_code": None,
            "checked": [SPECIAL],
        },
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
        other.validate(["En mer", "Lyon"], MER, None, None, "other")
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
    assert response.json() == {"added": 1, "conflicts": [conflict]}
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


def test_import_rejects_deeply_nested_json(client: TestClient) -> None:
    depth = 100_000
    content = b'{"places": ' + b"[" * depth + b"]" * depth + b"}"
    response = upload(client, content)
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Fichier illisible")


def test_import_counts_added_decisions(tmp_path: Path, client: TestClient) -> None:
    content = json.dumps(other_registry_document(tmp_path)).encode("utf-8")
    first = upload(client, content)
    assert first.json() == {"added": 2, "conflicts": []}
    again = upload(client, content)
    assert again.json() == {"added": 0, "conflicts": []}


@pytest.mark.parametrize("content", [b'{"format": "autre"}', b"[]"])
def test_import_format_error_is_french(client: TestClient, content: bytes) -> None:
    response = upload(client, content)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("Le fichier n'est pas un export de référentiel valide. (")
    assert detail.endswith(")")


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
    put = client.put(
        "/api/places/x/levels",
        json={"levels": [{"rank": 0, "name": "X"}], "postal_code": None},
        headers={"Origin": origin},
    )
    assert put.status_code == 403
    accept = client.post("/api/places/x/levels/0/accept", headers={"Origin": origin})
    assert accept.status_code == 403


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
    assert roubaix["view"]["department"] == "59"
    place_id = client.post(
        cluster_url(ROUBAIX, "validate"), json=validate_body(roubaix)
    ).json()["place_id"]
    return place_id, roubaix


def test_validate_without_a_level_removes_it_then_undo(
    client: TestClient, registry: PlaceRegistry
) -> None:
    place_id, roubaix = validated_roubaix(client)
    place_cluster = f"place:{place_id}"
    levels = [lv for lv in roubaix["levels"] if lv["type"] != "departement"]
    response = client.post(
        cluster_url(place_cluster, "validate"),
        json={
            "levels": levels,
            "postal_code": roubaix["postal_code"],
            "checked": writings_of(roubaix),
        },
    )
    assert response.status_code == 200, response.text
    place = registry.place(place_id)
    assert "department" not in place.fields
    assert "department" not in detail(client, place_cluster)["view_origins"]
    assert client.post("/api/undo").json() == {"action": "validate"}
    place = registry.place(place_id)
    assert place.fields["department"] == "59"
    assert detail(client, place_cluster)["view_origins"]["department"] == "insee"


def test_undo_ignores_entries_of_another_instance(
    tmp_path: Path,
    client: TestClient,
    registry: PlaceRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another process sharing the registry writes right after our action."""
    other = PlaceRegistry(tmp_path / "data" / "referentiel.sqlite")
    real_reject = registry.reject

    def reject_then_other(writings: list[str], project: str) -> int | None:
        entry = real_reject(writings, project)
        other.reject(["Ailleurs"], "other-process")
        return entry

    monkeypatch.setattr(registry, "reject", reject_then_other)
    response = client.post(cluster_url("name:en mer", "reject"))
    assert response.status_code == 200, response.text
    monkeypatch.undo()
    assert client.post("/api/undo").json() == {"action": "reject"}
    assert registry.decision("En mer") is None
    ailleurs = registry.decision("Ailleurs")
    assert ailleurs is not None and ailleurs.status == "rejected"
    other.close()


def test_partial_undo_keeps_the_rest_of_the_action(
    client: TestClient, registry: PlaceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    roubaix = detail(client, ROUBAIX)
    checked = [w for w in writings_of(roubaix) if w != "59512"]
    result = client.post(
        cluster_url(ROUBAIX, "validate"), json=validate_body(roubaix, checked)
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


# --- registry journal -------------------------------------------------------------


def journal(client: TestClient, query: str = "") -> list[dict[str, Any]]:
    response = client.get(f"/api/registry/journal{query}")
    assert response.status_code == 200, response.text
    entries: list[dict[str, Any]] = response.json()["entries"]
    return entries


def test_journal_lists_actions_newest_first(client: TestClient) -> None:
    assert journal(client) == []
    place_id, roubaix = validated_roubaix(client)
    client.post(cluster_url("name:en mer", "reject"))
    rubeacum = {"rank": 0, "name": "Rubeacum", "type": "lieu_dit"}
    client.put(
        f"/api/places/{place_id}/levels",
        json={
            "levels": [rubeacum, *roubaix["levels"]],
            "postal_code": roubaix["postal_code"],
        },
    )

    correct, reject, validate = journal(client)
    assert validate["action"] == "validate"
    assert validate["place_id"] == place_id
    assert validate["place_label"] == "Roubaix"
    assert validate["writings"] == sorted(writings_of(roubaix))
    assert validate["writing_count"] == len(writings_of(roubaix))
    assert validate["undone"] is False
    assert validate["undone_entry"] is None
    assert isinstance(validate["at"], str) and validate["at"]
    assert reject["action"] == "reject"
    assert reject["writings"] == ["En mer"]
    assert reject["place_id"] is None and reject["place_label"] is None
    assert correct["action"] == "correct"
    assert correct["writings"] == [] and correct["writing_count"] == 0
    assert correct["place_id"] == place_id
    assert correct["place_label"] == "Roubaix"
    assert correct["entry_id"] > reject["entry_id"] > validate["entry_id"]

    client.post("/api/undo")
    undo, correct_again, *_ = journal(client)
    assert undo["action"] == "undo"
    assert undo["undone_entry"] == correct["entry_id"]
    assert undo["place_id"] == place_id
    assert correct_again["undone"] is True


def test_journal_limit(client: TestClient, registry: PlaceRegistry) -> None:
    for name in ("A", "B", "C"):
        registry.reject([name], "p")
    assert [e["writings"] for e in journal(client, "?limit=2")] == [["C"], ["B"]]
    assert len(journal(client)) == 3
    for bad in ("0", "501", "x"):
        response = client.get(f"/api/registry/journal?limit={bad}")
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)


def test_journal_default_limit_is_50(
    client: TestClient, registry: PlaceRegistry
) -> None:
    for n in range(55):
        registry.reject([f"Lieu {n}"], "p")
    assert len(journal(client)) == 50
    assert len(journal(client, "?limit=500")) == 55


def test_journal_truncates_long_writing_lists(
    client: TestClient, registry: PlaceRegistry
) -> None:
    writings = [f"Lieu {n:02}" for n in range(30)]
    registry.reject(writings, "p")
    (entry,) = journal(client)
    assert entry["writing_count"] == 30
    assert entry["writings"] == writings[:20]


def test_journal_shows_import_and_resolve(
    tmp_path: Path, client: TestClient, registry: PlaceRegistry
) -> None:
    registry.reject(["En mer"], "p")
    document = other_registry_document(tmp_path)
    upload(client, json.dumps(document).encode("utf-8"))
    client.post(
        "/api/registry/conflicts/resolve",
        json={"writing": "En mer", "keep": "incoming"},
    )
    resolve, imported, _reject = journal(client)
    assert imported["action"] == "import"
    assert imported["writings"] == ["Lyon"]
    assert imported["place_label"] == "Mer"
    assert resolve["action"] == "resolve"
    assert resolve["writings"] == ["En mer"]
    assert resolve["place_label"] == "Mer"
