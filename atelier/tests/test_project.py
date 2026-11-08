import dataclasses
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from prosopo_gw_atelier.places.levels import Level, LevelOrigin, renumber
from prosopo_gw_atelier.project import ClusterView, Project
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store.registry import PlaceRegistry

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
def registry(tmp_path: Path, ref: RefData) -> Iterator[PlaceRegistry]:
    with PlaceRegistry(tmp_path / "data" / "referentiel.sqlite", ref) as reg:
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


def chain(*levels: tuple[str, str | None, str | None]) -> tuple[Level, ...]:
    """A manual chain from ``(name, type, identifier)`` triples, rank 0 first."""
    return renumber(
        [
            Level(0, name, type=type_, identifier=identifier, origin="manual")
            for name, type_, identifier in levels
        ]
    )


def commune(
    name: str, insee: str | None = None, department: str | None = None
) -> tuple[Level, ...]:
    """A manual chain: a commune, and its department when given."""
    levels: list[tuple[str, str | None, str | None]] = [(name, "commune", insee)]
    if department is not None:
        levels.append((department, "departement", department))
    return chain(*levels)


def validate(
    registry: PlaceRegistry,
    writings: list[str],
    levels: tuple[Level, ...],
    project: str,
    place_id: str | None = None,
    postal_code: str | None = None,
) -> str:
    """Validate ``writings`` to a place with ``levels``; returns the place id."""
    origin: LevelOrigin | None = "manual" if postal_code is not None else None
    return registry.validate(
        writings, levels, postal_code, origin, project, place_id=place_id
    ).place_id


def validate_view(registry: PlaceRegistry, view: ClusterView, project: str) -> str:
    """What the validation screen does with a cluster's chain, as shown."""
    origin: LevelOrigin | None = None
    if view.cluster.postal_code is not None:
        origin = (
            registry.place(view.place_id).postal_origin
            if view.from_registry and view.place_id is not None
            else "written"
        )
    return registry.validate(
        view.cluster.writings,
        view.cluster.levels,
        view.cluster.postal_code,
        origin,
        project,
        place_id=view.place_id if view.from_registry else None,
    ).place_id


def validate_all(project: Project, registry: PlaceRegistry) -> None:
    """What the validation screen does, cluster by cluster, with the chains."""
    for view in project.clusters():
        if view.needs_manual_levels:
            registry.reject(view.cluster.writings, project.project_id)
        else:
            validate_view(registry, view, project.project_id)


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
    validate(registry, ["Nowhere-sur-Mer"], commune("Nowhere"), "other")
    project = open_project(gw, registry, ref, projects_dir)
    every = [w for v in project.clusters() for w in v.cluster.writings]
    assert "Nowhere-sur-Mer" not in every


def test_cluster_states(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    pid = project.project_id
    registry.reject(["En mer"], pid)
    assert project.cluster("rejected:name:en mer").state == "rejected"

    # Part of a cluster decided: the undecided rest joins the place, still to do.
    roubaix = validate(registry, ["Roubaix"], commune("Roubaix"), pid)
    view = project.cluster(f"place:{roubaix}")
    assert view.cluster.writings == ROUBAIX_WRITINGS
    assert view.state == "todo"
    assert view.cluster.levels == commune("Roubaix")
    assert view.from_registry is True
    assert view.cluster.confidence == "high"

    # One place, decided by two projects: already decided.
    lille = project.cluster("insee:59350").cluster.writings
    place = validate(registry, ["Lille"], commune("Lille"), "other")
    validate(registry, [w for w in lille if w != "Lille"], commune("Lille"), pid, place)
    assert project.cluster(f"place:{place}").state == "already_decided"

    # Rejected by another project.
    registry.reject(["Merville"], "other")
    assert project.cluster("rejected:name:merville").state == "rejected"


def test_clusters_are_sorted_by_state_confidence_and_occurrences(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    ids = [v.cluster.id for v in project.clusters()]
    assert ids == [
        "insee:59512",  # high, 5 occurrences
        "insee:59350",  # high, 3 (Lomme is a former commune, apart)
        "insee:62765",  # high, 1
        "insee:69266",  # high, 1
        "insee:69123",  # medium, 2
        "historique:59355|lomme",  # medium, 1
        "insee:62041",  # medium, 1
        "name:en mer",  # low, 1
        "name:merville",  # low, 1
    ]
    pid = project.project_id
    registry.reject(["En mer"], pid)
    validate(registry, ["Arras"], commune("Arras"), pid)
    validate(registry, ["Lyon"], commune("Lyon"), "other")
    arras = registry.decision("Arras")
    lyon = registry.decision("Lyon")
    assert arras is not None and lyon is not None
    views = project.clusters()
    assert [v.cluster.id for v in views[-3:]] == [
        f"place:{lyon.place_id}",
        f"place:{arras.place_id}",
        "rejected:name:en mer",
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
    assert [lv.identifier for lv in new.cluster.levels if lv.type == "commune"] == [
        "59512"
    ]
    assert new.from_registry is False

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


def test_known_place_of_another_department_does_not_take_a_writing(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    validate(
        registry, ["Merville"], commune("Merville", department="31"), project.project_id
    )
    append(gw, "\nfam LEROY Marc 1880 #bp Merville,_Nord + FAURE Alice 1882\n")
    project.reload()
    view = view_of(project, "Merville, Nord")
    assert view.cluster.id == "insee:59400"
    assert view.place_id is None
    assert view_of(project, "Merville").cluster.writings == ["Merville"]


def test_merged_anchored_group_takes_the_lowest_confidence(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    place = validate(
        registry, ["En mer"], chain(("En mer", None, None)), project.project_id
    )
    append(gw, "\nfam LEROY Marc 1880 #bp EN_MER + FAURE Alice 1882\n")
    project.reload()
    view = view_of(project, "EN MER")
    assert view.cluster.id == f"place:{place}"
    assert view.cluster.writings == ["EN MER", "En mer"]
    assert view.state == "todo"
    assert view.cluster.confidence == "low"


def test_split_state_follows_the_registry(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["59512"])
    # A split is never anchored: the user separated it on purpose.
    assert new.cluster.anchor_place_id is None
    assert new.place_id is None
    place = validate(
        registry, ["59512"], commune("Roubaix", "59512"), project.project_id
    )
    view = project.cluster(new.cluster.id)
    assert view.state == "validated"
    # Once decided, the split shows its place, as the registry has it.
    assert view.place_id == place
    assert view.cluster.anchor_place_id is None
    assert view.cluster.levels == commune("Roubaix", "59512")
    assert view.from_registry is True
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
    place_id = validate(
        registry, ["Roubaix-Ville"], commune("Roubaix", "59512"), "other"
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
    p1 = validate(registry, one, commune("Roubaix"), first.project_id)
    p2 = validate(registry, two, commune("Roubaix", "59512"), first.project_id)
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
    assert b.cluster.levels == commune("Roubaix", "59512")
    with pytest.raises(KeyError):
        other.cluster("insee:59512")


def test_rejected_writing_never_joins_undecided_writings(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    registry.reject(["Roubaix"], "other")
    rejected = view_of(project, "Roubaix")
    assert rejected.cluster.id == "rejected:insee:59512"
    assert rejected.cluster.writings == ["Roubaix"]
    assert rejected.state == "rejected"
    assert "Roubaix" not in project.cluster("insee:59512").cluster.writings


def test_rejected_cluster_stays_one_cluster(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    """Rejected writings are grouped like undecided ones (``rejected:`` + id)."""
    project = open_project(gw, registry, ref, projects_dir)
    before = len(project.clusters())
    lille = project.cluster("insee:59350").cluster.writings
    assert len(lille) >= 3
    registry.reject(lille, project.project_id)
    views = project.clusters()
    assert len(views) == before
    rejected = [v for v in views if v.state == "rejected"]
    assert [v.cluster.id for v in rejected] == ["rejected:insee:59350"]
    assert rejected[0].cluster.writings == lille
    assert rejected[0].occurrences == 3


def test_split_follows_its_parent_when_the_grouping_changes(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    new = project.split("insee:59512", ["59512"])
    rest = [w for w in ROUBAIX_WRITINGS if w != "59512"]
    place = validate(registry, rest, commune("Roubaix"), project.project_id)
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
    view.cluster.levels = ()
    again = project.cluster("insee:59512").cluster
    assert again.writings == ROUBAIX_WRITINGS
    assert again.levels[0].name == "Roubaix"


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


# --- Level chains ------------------------------------------------------------------

HESDIN_GW = """encoding: utf-8
gwplus

fam DURAND Paul 1850 #bp Marconne,_Pas-de-Calais + LEFEBVRE Jeanne 1852
beg
- h Jacques 1876 #bp Hesdin-la-Forêt
end

pevt LEFEBVRE Jeanne
#birt 1852 #p Hesdin,_Pas-de-Calais
end pevt
"""


def test_marconne_and_hesdin_are_separate_clusters(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    gw = tmp_path / "bases" / "hesdin.gw"
    gw.parent.mkdir(parents=True)
    gw.write_text(HESDIN_GW, encoding="utf-8")
    project = open_project(gw, registry, ref, projects_dir)
    heads = {
        v.cluster.id: [(lv.name, lv.type) for lv in v.cluster.levels[:2]]
        for v in project.clusters()
    }
    assert heads == {
        "historique:62549|marconne": [
            ("Marconne", "commune_historique"),
            ("Hesdin-la-Forêt", "commune"),
        ],
        "historique:62447|hesdin": [
            ("Hesdin", "commune_historique"),
            ("Hesdin-la-Forêt", "commune"),
        ],
        "insee:62447": [
            ("Hesdin-la-Forêt", "commune"),
            ("Pas-de-Calais", "departement"),
        ],
    }
    marconne = project.cluster("historique:62549|marconne")
    assert marconne.from_registry is False
    place = validate_view(registry, marconne, project.project_id)
    view = project.cluster(f"place:{place}")
    assert view.from_registry is True
    # The place is that former commune: nothing to flag.
    assert view.historical_writings == {}
    assert view_of(project, "Hesdin-la-Forêt").place_id is None


def test_place_cluster_shows_registry_levels(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    rules = project.cluster("insee:59350").cluster.levels
    assert rules[0].name == "Lille"
    proposed = Level(0, "Fives", type="quartier", origin="rule", status="proposed")
    stored = renumber([proposed, *rules])
    place = validate(
        registry, ["Lille"], stored, project.project_id, postal_code="59000"
    )
    view = project.cluster(f"place:{place}")
    assert view.from_registry is True
    assert view.cluster.levels == registry.place(place).levels == stored
    assert view.cluster.levels[0].status == "proposed"
    assert view.cluster.postal_code == "59000"
    assert view.state == "todo"  # the other Lille writings joined it


def test_historical_writings_flag_merged_place(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    lille = project.cluster("insee:59350").cluster.levels
    # A version 1 place: Lomme validated with Lille, as the migration left it.
    place = validate(registry, ["Lille", "Lomme"], lille, project.project_id)
    view = project.cluster(f"place:{place}")
    assert "Lomme" in view.cluster.writings
    assert view.historical_writings == {"Lomme": "Lomme"}


def test_validating_onto_an_anchored_place_keeps_its_manual_level(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    stored = chain(("Le Hameau", "lieu_dit", None), ("Roubaix", "commune", "59512"))
    place = validate(registry, ["Roubaix-Ville"], stored, "other", postal_code="59101")
    project = open_project(gw, registry, ref, projects_dir)
    view = project.cluster("insee:59512")
    assert view.cluster.anchor_place_id == place
    assert view.place_id == place
    # The anchored cluster shows the place as stored, not the rules' chain.
    assert view.from_registry is True
    assert view.cluster.levels == stored
    assert view.cluster.postal_code == "59101"
    assert validate_view(registry, view, project.project_id) == place
    kept = registry.place(place)
    assert kept.levels == stored
    assert kept.levels[0].origin == "manual"
    assert (kept.postal_code, kept.postal_origin) == ("59101", "manual")
    assert project.cluster(f"place:{place}").state == "validated"


def test_cluster_of_unknown_codes_is_entered_by_hand(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    append(gw, "\npevt DUPONT Jean\n#buri 1910 #p 99999\nend pevt\n")
    project = open_project(gw, registry, ref, projects_dir)
    view = view_of(project, "99999")
    assert view.cluster.id == "name:99999"
    assert view.cluster.levels == ()
    assert view.needs_manual_levels is True
    assert view.state == "todo"
    assert view.from_registry is False
    others = [v for v in project.clusters() if v.cluster.id != "name:99999"]
    assert not any(v.needs_manual_levels for v in others)
    # A chain entered by hand makes it a place like any other.
    place = validate(registry, ["99999"], commune("Inconnu"), project.project_id)
    assert view_of(project, "99999").needs_manual_levels is False
    assert view_of(project, "99999").place_id == place
