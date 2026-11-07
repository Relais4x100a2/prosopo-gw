import dataclasses
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from prosopo_gw_atelier.places.model import ElementKind
from prosopo_gw_atelier.project import ClusterView, Project
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store.registry import Origin, PlaceRegistry

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINI = FIXTURES / "refdata_mini"

ROUBAIX_WRITINGS = [
    "59100 Roubaix",
    "59512",
    "ROUBAIX, Nord, France",
    "Roubaix",
    "roubaix, Nord-Pas-de-Calais",
]


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(MINI)


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "data" / "referentiel.sqlite") as reg:
        yield reg


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    return tmp_path / "data" / "projects"


@pytest.fixture
def gw(tmp_path: Path) -> Path:
    return copy_fixture(tmp_path, "lieux_varies.gw")


def copy_fixture(tmp_path: Path, name: str) -> Path:
    target = tmp_path / "bases" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / name, target)
    return target


def append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def replace(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new), encoding="utf-8")


ADD_ROUBAIX_59 = "\nfam GARNIER Luc 1888 #bp Roubaix_(59) + ROUSSEL Claire 1890\n"


def validate_all(project: Project, registry: PlaceRegistry) -> None:
    """What the validation screen does, cluster by cluster, with the proposals."""
    for view in project.clusters():
        cluster = view.cluster
        if cluster.proposal:
            origins: dict[ElementKind, Origin] = {k: "rule" for k in cluster.proposal}
            registry.validate(
                cluster.writings, cluster.proposal, origins, project.project_id
            )
        else:
            registry.reject(cluster.writings, project.project_id)


def states(project: Project) -> dict[str, str]:
    return {view.cluster.id: view.state for view in project.clusters()}


def view_of(project: Project, writing: str) -> ClusterView:
    (found,) = [v for v in project.clusters() if writing in v.cluster.writings]
    return found


def open_project(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> Project:
    return Project.open(gw, registry, ref, projects_dir)


# --- opening -------------------------------------------------------------------


def test_open_exposes_tables_writings_and_clusters(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    assert {table.spec.name for table in project.tables} >= {"personnes", "evenements"}
    assert len(project.writings["Lyon"].occurrences) == 2
    roubaix = project.cluster("insee:59512")
    assert roubaix.cluster.writings == ROUBAIX_WRITINGS
    assert roubaix.state == "todo"
    assert roubaix.occurrences == 5
    assert roubaix.parent_id is None
    assert roubaix.provisional_name is None
    every = [w for v in project.clusters() for w in v.cluster.writings]
    assert sorted(every) == sorted(project.writings)


def test_project_id_is_a_fingerprint_of_the_absolute_path(
    gw: Path,
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    assert len(project.project_id) == 16
    int(project.project_id, 16)
    assert (projects_dir / f"{project.project_id}.sqlite").is_file()
    monkeypatch.chdir(gw.parent)
    again = open_project(Path(gw.name), registry, ref, projects_dir)
    assert again.project_id == project.project_id
    other = open_project(
        copy_fixture(tmp_path / "other", "lieux_varies.gw"),
        registry,
        ref,
        projects_dir,
    )
    assert other.project_id != project.project_id


def test_unknown_cluster_raises_key_error(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    with pytest.raises(KeyError):
        project.cluster("insee:00000")


# --- Step 1: no decision to redo ----------------------------------------------


def test_no_decision_to_redo(
    gw: Path,
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    validate_all(project, registry)
    # Decisions are read at call time.
    assert set(states(project).values()) == {"validated"}

    reopened = open_project(gw, registry, ref, projects_dir)
    assert set(states(reopened).values()) == {"validated"}

    append(gw, ADD_ROUBAIX_59)
    modified = open_project(gw, registry, ref, projects_dir)
    todo = [v for v in modified.clusters() if v.state == "todo"]
    assert len(todo) == 1
    (roubaix,) = todo
    assert "Roubaix (59)" in roubaix.cluster.writings
    decision = registry.decision("Roubaix")
    assert decision is not None
    assert roubaix.cluster.anchor_place_id == decision.place_id
    assert {
        v.state for v in modified.clusters() if v.cluster.id != roubaix.cluster.id
    } == {"validated"}

    other = open_project(
        copy_fixture(tmp_path, "autre_base.gw"), registry, ref, projects_dir
    )
    assert other.project_id != project.project_id
    assert view_of(other, "Lyon").state == "already_decided"
    assert view_of(other, "Fictiville").state == "todo"


def test_reload_reapplies_decisions(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    validate_all(project, registry)
    append(gw, ADD_ROUBAIX_59)
    assert "Roubaix (59)" not in project.writings
    project.reload()
    assert "Roubaix (59)" in project.writings
    decision = registry.decision("Roubaix")
    assert decision is not None
    assert [v.cluster.id for v in project.clusters() if v.state == "todo"] == [
        f"place:{decision.place_id}"
    ]


def test_writing_of_the_registry_absent_from_the_gw_is_ignored(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    registry.validate(
        ["Nowhere-sur-Mer"], {"commune": "Nowhere"}, {"commune": "manual"}, "other"
    )
    project = open_project(gw, registry, ref, projects_dir)
    every = [w for v in project.clusters() for w in v.cluster.writings]
    assert "Nowhere-sur-Mer" not in every


def test_cluster_states(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    pid = project.project_id
    registry.reject(["En mer"], pid)
    assert project.cluster("rejected:en mer").state == "rejected"

    # Part of a cluster decided: the undecided rest joins the place, still to do.
    roubaix = registry.validate(
        ["Roubaix"], {"commune": "Roubaix"}, {"commune": "rule"}, pid
    )
    view = project.cluster(f"place:{roubaix}")
    assert view.cluster.writings == ROUBAIX_WRITINGS
    assert view.state == "todo"
    assert view.cluster.proposal == {"commune": "Roubaix"}
    assert view.cluster.confidence == "high"

    # One place, decided by two projects: already decided.
    lille = project.cluster("insee:59350").cluster.writings
    place = registry.validate(
        ["Lille"], {"commune": "Lille"}, {"commune": "rule"}, "other"
    )
    registry.validate(
        [w for w in lille if w != "Lille"],
        {"commune": "Lille"},
        {"commune": "rule"},
        pid,
        place_id=place,
    )
    assert project.cluster(f"place:{place}").state == "already_decided"

    # Rejected by another project.
    registry.reject(["Merville"], "other")
    assert project.cluster("rejected:merville").state == "rejected"


def test_clusters_are_sorted_by_state_confidence_and_occurrences(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    ids = [v.cluster.id for v in project.clusters()]
    assert ids == [
        "insee:59512",  # high, 5 occurrences
        "insee:59350",  # high, 4
        "insee:62765",  # high, 1
        "insee:69266",  # high, 1
        "insee:69123",  # medium, 2
        "insee:62041",  # medium, 1
        "name:en mer",  # low, 1
        "name:merville",  # low, 1
    ]
    pid = project.project_id
    registry.reject(["En mer"], pid)
    registry.validate(["Arras"], {"commune": "Arras"}, {"commune": "rule"}, pid)
    registry.validate(["Lyon"], {"commune": "Lyon"}, {"commune": "rule"}, "other")
    arras = registry.decision("Arras")
    lyon = registry.decision("Lyon")
    assert arras is not None and lyon is not None
    views = project.clusters()
    assert [v.cluster.id for v in views[-3:]] == [
        f"place:{lyon.place_id}",
        f"place:{arras.place_id}",
        "rejected:en mer",
    ]
    assert [v.state for v in views[-3:]] == [
        "already_decided",
        "validated",
        "rejected",
    ]


# --- Step 2: split -------------------------------------------------------------


def test_split_follows_its_parent(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["roubaix, Nord-Pas-de-Calais", "59512"])
    assert new.cluster.id.startswith("split:")
    assert new.parent_id == "insee:59512"
    assert new.provisional_name == "roubaix, Nord-Pas-de-Calais"
    assert new.cluster.writings == ["59512", "roubaix, Nord-Pas-de-Calais"]
    assert new.state == "todo"
    assert new.occurrences == 2
    assert new.cluster.proposal["insee_code"] == "59512"

    ids = [v.cluster.id for v in project.clusters()]
    assert ids[ids.index("insee:59512") + 1] == new.cluster.id
    parent = project.cluster("insee:59512")
    assert parent.cluster.writings == [
        "59100 Roubaix",
        "ROUBAIX, Nord, France",
        "Roubaix",
    ]
    assert parent.occurrences == 3
    assert project.cluster(new.cluster.id) == new


def test_split_survives_reload_and_reopen(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["Roubaix", "59100 Roubaix"])
    project.reload()
    assert project.cluster(new.cluster.id) == new
    reopened = open_project(gw, registry, ref, projects_dir)
    assert reopened.cluster(new.cluster.id) == new
    assert "Roubaix" not in reopened.cluster("insee:59512").cluster.writings


def test_split_drops_writings_gone_from_the_gw(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["59100 Roubaix", "Roubaix"])
    replace(gw, "#p 59100_Roubaix", "#p Arras")
    project.reload()
    kept = project.cluster(new.cluster.id)
    assert kept.cluster.writings == ["Roubaix"]
    assert kept.provisional_name == "Roubaix"

    replace(gw, "#mp Roubaix", "#mp Arras")
    replace(gw, "#p Roubaix", "#p Arras")
    project.reload()
    assert "Roubaix" not in project.writings
    with pytest.raises(KeyError):
        project.cluster(new.cluster.id)
    assert all(not v.cluster.id.startswith("split:") for v in project.clusters())


def test_unsplit_removes_the_split_and_persists(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    before = project.cluster("insee:59512")
    new = project.split("insee:59512", ["Roubaix", "59100 Roubaix"])
    project.unsplit(new.cluster.id)
    with pytest.raises(KeyError):
        project.cluster(new.cluster.id)
    assert project.cluster("insee:59512") == before
    reopened = open_project(gw, registry, ref, projects_dir)
    assert reopened.cluster("insee:59512") == before
    assert all(not v.cluster.id.startswith("split:") for v in reopened.clusters())
    with sqlite3.connect(project.state_path) as conn:
        for table in ("splits", "split_writings", "split_parent_writings"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_unsplit_of_an_unknown_split_raises_key_error(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    with pytest.raises(KeyError):
        project.unsplit("split:absent")


def test_decomposition_of_a_writing(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    decomposition = project.decomposition("59100 Roubaix")
    assert decomposition.writing == "59100 Roubaix"
    assert decomposition.insee == "59512"
    with pytest.raises(KeyError):
        project.decomposition("Nulle Part")


def test_split_of_a_split(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    first = project.split("insee:59512", ["Roubaix", "59512", "59100 Roubaix"])
    second = project.split(first.cluster.id, ["59512"])
    assert second.parent_id == first.cluster.id
    ids = [v.cluster.id for v in project.clusters()]
    at = ids.index("insee:59512")
    assert ids[at : at + 3] == ["insee:59512", first.cluster.id, second.cluster.id]
    assert project.cluster(first.cluster.id).cluster.writings == [
        "59100 Roubaix",
        "Roubaix",
    ]
    reopened = open_project(gw, registry, ref, projects_dir)
    assert reopened.cluster(second.cluster.id) == second
    assert reopened.cluster(first.cluster.id) == project.cluster(first.cluster.id)


def test_split_state_follows_the_registry(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["59512"])
    registry.validate(
        ["59512"], {"insee_code": "59512"}, {"insee_code": "rule"}, project.project_id
    )
    assert project.cluster(new.cluster.id).state == "validated"
    assert view_of(project, "Roubaix").state == "todo"


@pytest.mark.parametrize(
    "writings",
    [[], ROUBAIX_WRITINGS, ["Lyon"], ["Roubaix", "Nowhere"]],
    ids=["empty", "all", "foreign", "unknown"],
)
def test_split_rejects_invalid_writings(
    gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    writings: list[str],
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    with pytest.raises(ValueError):
        project.split("insee:59512", writings)
    assert all(not v.cluster.id.startswith("split:") for v in project.clusters())


def test_split_of_an_unknown_cluster_raises_key_error(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    with pytest.raises(KeyError):
        project.split("insee:00000", ["Roubaix"])


# --- Step 3: gw_changed ----------------------------------------------------------


def test_gw_changed(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    assert open_project(gw, registry, ref, projects_dir).gw_changed is False
    project = open_project(gw, registry, ref, projects_dir)
    assert project.gw_changed is False

    append(gw, ADD_ROUBAIX_59)
    assert open_project(gw, registry, ref, projects_dir).gw_changed is True
    assert open_project(gw, registry, ref, projects_dir).gw_changed is False

    project.reload()
    assert project.gw_changed is False
    append(gw, "\nfam GARNIER Paul 1890 + ROUSSEL Anne 1891\n")
    project.reload()
    assert project.gw_changed is True
    project.reload()
    assert project.gw_changed is False


def test_project_state_file_records_path_and_fingerprint(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    db = projects_dir / f"{project.project_id}.sqlite"
    with sqlite3.connect(db) as conn:
        path, sha = conn.execute("SELECT path, sha256 FROM project").fetchone()
    conn.close()
    assert path == str(gw.resolve())
    assert len(sha) == 64


def test_anchor_follows_the_registry_without_reload(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    assert project.cluster("insee:59512").cluster.anchor_place_id is None
    # The place has no writing in this .gw: the anchored cluster keeps its id.
    place_id = registry.validate(
        ["Roubaix-Ville"],
        {"commune": "Roubaix", "insee_code": "59512"},
        {"commune": "rule", "insee_code": "rule"},
        "other",
    )
    view = project.cluster("insee:59512")
    assert view.cluster.anchor_place_id == place_id
    assert view.state == "todo"


# --- Fix round 1: decided writings attached to their place -------------------


def test_writings_validated_to_two_places_stay_apart(
    gw: Path,
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
) -> None:
    first = open_project(gw, registry, ref, projects_dir)
    one = ["Roubaix", "roubaix, Nord-Pas-de-Calais"]
    two = ["59100 Roubaix", "59512", "ROUBAIX, Nord, France"]
    p1 = registry.validate(
        one, {"commune": "Roubaix"}, {"commune": "manual"}, first.project_id
    )
    p2 = registry.validate(
        two,
        {"commune": "Roubaix", "insee_code": "59512"},
        {"commune": "rule", "insee_code": "rule"},
        first.project_id,
    )
    assert first.cluster(f"place:{p1}").state == "validated"

    other = open_project(
        copy_fixture(tmp_path / "other", "lieux_varies.gw"),
        registry,
        ref,
        projects_dir,
    )
    a, b = other.cluster(f"place:{p1}"), other.cluster(f"place:{p2}")
    assert a.cluster.writings == sorted(one)
    assert b.cluster.writings == two
    assert (a.state, b.state) == ("already_decided", "already_decided")
    assert a.cluster.anchor_place_id == p1
    assert b.cluster.proposal == {"commune": "Roubaix", "insee_code": "59512"}
    with pytest.raises(KeyError):
        other.cluster("insee:59512")


def test_rejected_writing_never_joins_undecided_writings(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    registry.reject(["Roubaix"], "other")
    rejected = view_of(project, "Roubaix")
    assert rejected.cluster.id == "rejected:roubaix"
    assert rejected.cluster.writings == ["Roubaix"]
    assert rejected.state == "rejected"
    assert "Roubaix" not in project.cluster("insee:59512").cluster.writings


def test_split_follows_its_parent_when_the_grouping_changes(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["59512"])
    rest = [w for w in ROUBAIX_WRITINGS if w != "59512"]
    place = registry.validate(
        rest, {"commune": "Roubaix"}, {"commune": "rule"}, project.project_id
    )
    project.reload()
    ids = [v.cluster.id for v in project.clusters()]
    assert "insee:59512" not in ids
    assert project.cluster(new.cluster.id).parent_id == f"place:{place}"
    assert ids[ids.index(f"place:{place}") + 1] == new.cluster.id
    reopened = open_project(gw, registry, ref, projects_dir)
    assert reopened.cluster(new.cluster.id).parent_id == f"place:{place}"


def test_split_without_any_parent_left_is_top_level(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["Roubaix"])
    for old, fresh in [
        ("#p 59100_Roubaix", "#p Arras"),
        ("#p 59512", "#p Arras"),
        ("#p ROUBAIX,_Nord,_France", "#p Arras"),
        ("#bp roubaix,_Nord-Pas-de-Calais", "#bp Arras"),
    ]:
        replace(gw, old, fresh)
    project.reload()
    assert project.cluster(new.cluster.id).parent_id is None


def test_views_are_frozen_and_do_not_share_the_cache(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    view = project.cluster("insee:59512")
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.state = "validated"  # type: ignore[misc]
    view.cluster.writings.append("Nowhere")
    view.cluster.proposal["commune"] = "Nowhere"
    again = project.cluster("insee:59512").cluster
    assert again.writings == ROUBAIX_WRITINGS
    assert again.proposal["commune"] == "Roubaix"


def test_state_file_of_version_1_is_migrated(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["Roubaix"])
    db = projects_dir / f"{project.project_id}.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE split_parent_writings")
        conn.execute("PRAGMA user_version = 1")
    conn.close()
    reopened = open_project(gw, registry, ref, projects_dir)
    assert reopened.cluster(new.cluster.id).parent_id == "insee:59512"
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    conn.close()
