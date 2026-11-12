import dataclasses
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from prosopo_gw_atelier.places import precision as precision_module
from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.levels import (
    Level,
    LevelOrigin,
    check_chain,
    renumber,
    rule_levels,
)
from prosopo_gw_atelier.project import (
    ClusterView,
    CountryRow,
    Project,
    _revert_refused,
)
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.refdata.paris_table import ParisTable, load_paris_table
from prosopo_gw_atelier.sources.base import LevelQuery, SourceCandidate
from prosopo_gw_atelier.sources.geonames.index import GeoNamesIndex
from prosopo_gw_atelier.sources.geonames.source import GEONAMES, GeoNamesSource
from prosopo_gw_atelier.store.config import LocalConfig
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


def test_historical_writings_follow_the_place_s_own_former_commune(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = open_project(gw, registry, ref, projects_dir)
    pid = project.project_id
    lille = project.cluster("insee:59350").cluster.levels
    lomme = Level(
        0, "Lomme", type="commune_historique", identifier="59355", status="proposed"
    )
    # As the migration leaves a v1 place: Lomme proposed above Lille.
    place = validate(registry, ["Lille", "Lomme"], renumber([lomme, *lille]), pid)
    view = project.cluster(f"place:{place}")
    assert view.historical_writings == {"Lomme": "Lomme"}
    # Once Lomme is the place, the Lille writing is the odd one out.
    registry.accept_proposal(place, 0, pid)
    view = project.cluster(f"place:{place}")
    assert view.cluster.levels[0].status == "validated"
    assert view.historical_writings == {"Lille": "Lille"}
    # Not only ``place:`` clusters: a split of the place is that place too.
    split = project.split(f"place:{place}", ["Lille"])
    assert split.place_id == place
    assert split.historical_writings == {"Lille": "Lille"}
    assert project.cluster(f"place:{place}").historical_writings == {}


def test_validating_onto_an_anchored_place_keeps_its_manual_level(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    stored = chain(("Roubaix", "commune", "59512"), ("Ferrain", None, None))
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


def test_commune_writings_do_not_anchor_on_a_finer_place(
    gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    stored = chain(("Le Hameau", "lieu_dit", None), ("Roubaix", "commune", "59512"))
    validate(registry, ["Roubaix-Ville"], stored, "other")
    project = open_project(gw, registry, ref, projects_dir)
    view = project.cluster("insee:59512")
    assert view.cluster.anchor_place_id is None
    assert view.from_registry is False
    assert (view.cluster.levels[0].name, view.cluster.levels[0].type) == (
        "Roubaix",
        "commune",
    )


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
    pid = project.project_id
    # Proposed levels only: nothing validated to accept yet.
    proposed = (Level(0, "Inconnu", origin="manual", status="proposed"),)
    place = validate(registry, ["99999"], proposed, pid)
    assert view_of(project, "99999").place_id == place
    assert view_of(project, "99999").needs_manual_levels is True
    # A chain entered by hand makes it a place like any other.
    validate(registry, ["99999"], commune("Inconnu"), pid, place)
    assert view_of(project, "99999").needs_manual_levels is False
    # A rejected cluster carries no levels, on purpose.
    registry.reject(["99999"], pid)
    rejected = view_of(project, "99999")
    assert rejected.cluster.levels == ()
    assert rejected.needs_manual_levels is False


# --- Step 2: arrondissement precisions -------------------------------------------


@pytest.fixture(scope="module")
def paris_table() -> ParisTable:
    return load_paris_table(FIXTURES / "paris_mini")


def paris_project(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> Project:
    gw = copy_fixture(tmp_path, "paris_precisions.gw")
    return Project.open(gw, registry, ref, projects_dir, paris_table=paris_table)


def summary(project: Project) -> list[tuple[str, str | None, str, str, str]]:
    return [
        (
            p.writing,
            p.occurrence.complement,
            p.precision.period,
            p.precision.status,
            ",".join(c.arrondissement_id for c in p.precision.candidates),
        )
        for p in project.precisions()
    ]


def test_precisions_of_fixture(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    assert summary(project) == [
        (
            "75007 Paris",
            "rue de Vaugirard",
            "paris-1860",
            "conflict",
            "75107,75106,75115",
        ),
        (
            "Paris",
            "12 rue Saint-Honoré",
            "paris-1795",
            "ambiguous",
            "paris-1795-02,paris-1795-04",
        ),
        ("Paris", "rue Tournon", "paris-1860", "applied", "75106"),
        ("Paris 7e", None, "", "applied", "paris-07"),
        ("Paris 7e", None, "paris-1795", "applied", "paris-1795-07"),
        ("Paris 7e", None, "paris-1860", "applied", "75107"),
    ]
    first = project.precisions()[0]
    assert first.place_id is None
    assert first.occurrence.table == "personnes"


def test_stored_decision_wins(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    pid = project.project_id
    registry.decide_precision(
        "75007 Paris", "rue de Vaugirard", "paris-1860", "75115", "paris-q-necker", pid
    )
    (decided,) = [p for p in project.precisions() if p.writing == "75007 Paris"]
    assert decided.precision.status == "applied"
    (candidate,) = decided.precision.candidates
    assert (candidate.arrondissement_id, candidate.quartier_id, candidate.clue) == (
        "75115",
        "paris-q-necker",
        "manual",
    )
    # Cleared: the computed conflict is back.
    registry.clear_precision("75007 Paris", "rue de Vaugirard", "paris-1860", pid)
    (back,) = [p for p in project.precisions() if p.writing == "75007 Paris"]
    assert back.precision.status == "conflict"


def test_stored_decision_keeps_the_quartier_name(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    named = [
        (c.arrondissement_id, c.quartier_id, c.quartier)
        for p in project.precisions()
        for c in p.precision.candidates
        if c.quartier_id and c.quartier
    ]
    assert named, "the fixture should offer a named quartier"
    arrondissement_id, quartier_id, name = named[0]
    group = next(
        p
        for p in project.precisions()
        if any(c.quartier_id == quartier_id for c in p.precision.candidates)
    )
    registry.decide_precision(
        group.writing,
        group.occurrence.complement,
        group.precision.period,
        arrondissement_id,
        quartier_id,
        project.project_id,
    )
    (candidate,) = next(
        p
        for p in project.precisions()
        if (p.writing, p.occurrence.complement, p.precision.period)
        == (group.writing, group.occurrence.complement, group.precision.period)
    ).precision.candidates
    assert (candidate.clue, candidate.quartier) == ("manual", name)


def test_stored_decision_without_arrondissement(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    registry.decide_precision(
        "75007 Paris", "rue de Vaugirard", "paris-1860", None, None, project.project_id
    )
    (decided,) = [p for p in project.precisions() if p.writing == "75007 Paris"]
    assert decided.precision.status == "applied"
    (candidate,) = decided.precision.candidates
    assert (candidate.arrondissement_id, candidate.quartier_id) == ("", None)
    assert candidate.clue == "manual"


def test_undo_of_a_precision_decision_refreshes(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    entry = registry.decide_precision(
        "75007 Paris",
        "rue de Vaugirard",
        "paris-1860",
        "75115",
        None,
        project.project_id,
    )
    assert entry is not None
    assert "applied" in {p.precision.status for p in project.precisions()}
    registry.undo(entry)
    assert [p.precision.status for p in project.precisions()].count("conflict") == 1


def test_precision_groups_gather_same_value(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    gw = copy_fixture(tmp_path, "paris_precisions.gw")
    append(
        gw,
        "\npevt DUPONT Marie\n#birt 1851 #p Paris_7e\nend pevt\n"
        "pevt DUPONT Lucie\n#birt 1900 #p [rue_de_Vaugirard]_-_75007_Paris\nend pevt\n",
    )
    project = Project.open(gw, registry, ref, projects_dir, paris_table=paris_table)
    groups = project.precision_groups({"conflict", "ambiguous"})
    assert [
        (g.writing, g.complement, g.period, g.status, g.occurrences) for g in groups
    ] == [
        ("75007 Paris", "rue de Vaugirard", "paris-1860", "conflict", 2),
        ("Paris", "12 rue Saint-Honoré", "paris-1795", "ambiguous", 1),
    ]
    assert {c.clue for c in groups[0].candidates} == {"code", "street"}
    everything = project.precision_groups(
        {"applied", "conflict", "ambiguous", "uncertain"}
    )
    paris7_old = [
        g for g in everything if g.writing == "Paris 7e" and g.period == "paris-1795"
    ]
    assert [g.occurrences for g in paris7_old] == [2]
    assert project.precision_groups(set()) == []


def test_undecided_precision_group_ignores_stored_decisions(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    key = ("75007 Paris", "rue de Vaugirard", "paris-1860")
    before = project.undecided_precision_group(*key)
    assert before is not None
    assert before.status == "conflict"
    registry.decide_precision(*key, "75115", None, project.project_id)
    after = project.undecided_precision_group(*key)
    assert after == before
    assert project.undecided_precision_group("Nulle part", "", "paris-1860") is None


def test_paris_place_flags_arrondissement_writings(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    place_id = validate(
        registry, ["Paris", "Paris 7e"], commune("Paris", "75056"), project.project_id
    )
    view = project.cluster(f"place:{place_id}")
    assert view.historical_writings == {"Paris 7e": "7e arrondissement"}
    # With an arrondissement level the place is not flagged.
    levels = chain(
        ("7e arrondissement", "arrondissement", "paris-07"),
        ("Paris", "commune", "75056"),
    )
    registry.set_levels(place_id, levels, None, None, project.project_id)
    assert project.cluster(f"place:{place_id}").historical_writings == {}


def test_precisions_are_cached_until_reload(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    paris_table: ParisTable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = paris_project(tmp_path, registry, ref, projects_dir, paris_table)
    calls = 0
    real = precision_module.precise

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("prosopo_gw_atelier.project.precise", counting)
    first = project.precisions()
    assert calls > 0
    done = calls
    assert project.precisions() == first
    project.precision_groups({"conflict"})
    assert calls == done
    project.reload()
    project.precisions()
    assert calls > done


# --- source proposals (DicoTopo overlay) -------------------------------------

from prosopo_gw_atelier.sources.dicotopo.index import DicoTopoIndex  # noqa: E402
from prosopo_gw_atelier.sources.dicotopo.source import (  # noqa: E402
    DICOTOPO,
    DicoTopoSource,
)
from prosopo_gw_atelier.sources.queue import SourceQueue, Worker, handle_match  # noqa: E402

HAMLET = "Fictimont, Hesdin-la-Forêt"


@pytest.fixture
def queue(tmp_path: Path) -> SourceQueue:
    return SourceQueue(tmp_path / "data" / "queue.sqlite")


@pytest.fixture
def dicotopo(tmp_path: Path, ref: RefData) -> DicoTopoSource:
    index = DicoTopoIndex(tmp_path / "dt.sqlite")
    index.add_department("62", FIXTURES / "dicotopo" / "DT62.xml", "2026-11-08")
    return DicoTopoSource(index, ref, api_enabled=False)


@pytest.fixture
def hamlet_gw(tmp_path: Path) -> Path:
    return copy_fixture(tmp_path, "lieux_dicotopo.gw")


def worker_for(queue: SourceQueue, source: DicoTopoSource) -> Worker:
    return Worker(
        queue,
        {
            (DICOTOPO, "match"): lambda job: handle_match(
                job, source=source, queue=queue
            )
        },
    )


def drain(worker: Worker) -> int:
    count = 0
    while worker.run_once():
        count += 1
    return count


def attached(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    source: DicoTopoSource,
) -> Project:
    project = Project.open(hamlet_gw, registry, ref, projects_dir)
    project.attach_sources(queue, {DICOTOPO: source})
    return project


def hamlet_view(project: Project) -> ClusterView:
    return next(v for v in project.clusters() if HAMLET in v.cluster.writings)


def test_project_overlays_dicotopo_proposal(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    assert hamlet_view(project).pending_sources == (DICOTOPO,)
    assert drain(worker_for(queue, dicotopo)) >= 1
    view = hamlet_view(project)
    assert view.pending_sources == ()
    first = view.cluster.levels[0]
    assert (first.name, first.type, first.origin, first.status) == (
        "Fictimont",
        "hameau",
        "dicotopo",
        "proposed",
    )
    assert first.identifier == "P90000002"
    assert view.alternatives == ()
    # reload keeps (and re-reads) the cached results: nothing pending
    project.reload()
    assert hamlet_view(project).cluster.levels[0].status == "proposed"


def test_refused_proposal_stays_refused(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    drain(worker_for(queue, dicotopo))
    view = hamlet_view(project)
    assert view.cluster.levels[0].status == "proposed"
    for writing in view.cluster.writings:
        registry.refuse_source_proposal(
            f"writing:{writing}", DICOTOPO, "P90000002", project.project_id
        )
    assert all(lv.origin != "dicotopo" for lv in hamlet_view(project).cluster.levels)
    project.reload()
    queue.clear(DICOTOPO)
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    drain(worker_for(queue, dicotopo))
    assert all(lv.origin != "dicotopo" for lv in hamlet_view(project).cluster.levels)


def test_refusal_by_place_subject_and_undo(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    drain(worker_for(queue, dicotopo))
    view = hamlet_view(project)
    place = registry.validate(
        view.cluster.writings,
        rule_levels(decompose(HAMLET, ref), ref),
        None,
        None,
        project.project_id,
    ).place_id
    # validated place: the proposal is still overlaid on its chain, subject place:
    view = hamlet_view(project)
    assert view.place_id == place
    assert any(lv.origin == "dicotopo" for lv in view.cluster.levels)
    entry = registry.refuse_source_proposal(
        f"place:{place}", DICOTOPO, "P90000002", project.project_id
    )
    assert entry is not None
    assert all(lv.origin != "dicotopo" for lv in hamlet_view(project).cluster.levels)
    registry.undo(entry)
    assert any(lv.origin == "dicotopo" for lv in hamlet_view(project).cluster.levels)


def test_opened_cluster_is_matched_first(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    queue.enqueue(DICOTOPO, "match", "competitor", {"name": "zz"}, 5)
    # without touch the competitor (priority 5) would come first
    project.touch(hamlet_view(project).cluster.id)
    job = queue.next_job()
    assert job is not None
    assert json_name(job.payload) == "Fictimont"


def json_name(payload: dict[str, object]) -> object:
    return payload["name"]


def test_overlay_does_not_write_registry(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    before = registry.journal()
    places = registry.places()
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    drain(worker_for(queue, dicotopo))
    hamlet_view(project)
    assert registry.journal() == before
    assert registry.places() == places


def test_no_sources_attached_changes_nothing(
    hamlet_gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = Project.open(hamlet_gw, registry, ref, projects_dir)
    view = hamlet_view(project)
    assert view.pending_sources == ()
    assert all(lv.origin != "dicotopo" for lv in view.cluster.levels)
    project.touch(view.cluster.id)  # no-op without a queue


def test_unanswerable_query_is_not_cached_then_proposed_after_indexing(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    tmp_path: Path,
) -> None:
    index = DicoTopoIndex(tmp_path / "empty.sqlite")
    source = DicoTopoSource(index, ref, api_enabled=False)
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, source)
    drain(worker_for(queue, source))
    view = hamlet_view(project)
    assert all(lv.origin != "dicotopo" for lv in view.cluster.levels)
    assert queue.epochs()[0] == 0  # nothing stored: no empty result cached
    # the department gets indexed (what handle_index does), the next pass asks again
    index.add_department("62", FIXTURES / "dicotopo" / "DT62.xml", "2026-11-08")
    queue.clear_results(DICOTOPO, "62")
    hamlet_view(project)
    drain(worker_for(queue, source))
    assert hamlet_view(project).cluster.levels[0].origin == "dicotopo"


def test_failed_job_is_reported_not_pending(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)

    job = queue.next_job()
    assert job is not None
    for _ in range(4):  # three back-offs, then failed for good
        with queue._db() as db:  # test only: make the retry due at once
            db.execute("UPDATE jobs SET not_before=NULL, state='running'")
        queue.fail(job.id, "boom")
    view = hamlet_view(project)
    assert view.failed_sources == (DICOTOPO,)
    assert view.pending_sources == ()


def test_refusal_made_before_validation_survives_it(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    drain(worker_for(queue, dicotopo))
    view = hamlet_view(project)
    for writing in view.cluster.writings:
        registry.refuse_source_proposal(
            f"writing:{writing}", DICOTOPO, "P90000002", project.project_id
        )
    registry.validate(
        view.cluster.writings,
        rule_levels(decompose(HAMLET, ref), ref),
        None,
        None,
        project.project_id,
    )
    after = hamlet_view(project)
    assert after.place_id is not None
    assert all(lv.origin != "dicotopo" for lv in after.cluster.levels)


def test_validate_path_does_not_save_overlay_levels(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    from prosopo_gw_atelier.web.app import _strip_overlay

    project = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    drain(worker_for(queue, dicotopo))
    view = hamlet_view(project)
    assert view.cluster.levels[0].origin == "dicotopo"
    kept = _strip_overlay(view.cluster.levels, view)
    assert all(lv.origin != "dicotopo" for lv in kept)
    assert [lv.rank for lv in kept] == list(range(len(kept)))
    assert kept[0].name == view.base_levels[0].name


def test_queue_results_batch_and_clear(
    registry: PlaceRegistry, queue: SourceQueue
) -> None:
    import json

    k1 = json.dumps({"department": "62", "name": "a"}, sort_keys=True)
    k2 = json.dumps({"department": "59", "name": "b"}, sort_keys=True)
    queue.store_result(DICOTOPO, k1, [])
    queue.store_result(DICOTOPO, k2, [])
    assert set(queue.results(DICOTOPO, [k1, k2, "absent"])) == {k1, k2}
    assert queue.clear_results(DICOTOPO, "62") == 1
    assert set(queue.results(DICOTOPO, [k1, k2])) == {k2}


# --- GeoNames mode per country and per place -----------------------------------

GN = FIXTURES / "geonames"
WINNIPEG = "Winnipeg, , , Manitoba, Canada"
WINNIPEG2 = "Winnipeg, Manitoba, Canada"
STORRINGTON = "Storrington, , East Sussex, England, Royaume-Uni"
KONIGSBERG = "Königsberg, Prusse"


@pytest.fixture
def geo_index(tmp_path: Path) -> GeoNamesIndex:
    index = GeoNamesIndex(tmp_path / "geonames")
    for cc in ("CA", "GB"):
        index.build(
            cc,
            GN / f"{cc}.zip",
            GN / "admin1CodesASCII.txt",
            GN / "admin2Codes.txt",
            "2026-11-08",
        )
    return index


@pytest.fixture
def geo_source(tmp_path: Path, geo_index: GeoNamesIndex) -> GeoNamesSource:
    return GeoNamesSource(
        geo_index, config=LocalConfig(), counter_path=tmp_path / "api_counter.json"
    )


@pytest.fixture
def geo_gw(tmp_path: Path) -> Path:
    return copy_fixture(tmp_path, "lieux_geonames.gw")


def geo_worker(queue: SourceQueue, source: GeoNamesSource) -> Worker:
    return Worker(
        queue,
        {
            (GEONAMES, "match"): lambda job: handle_match(
                job, source=source, queue=queue
            )
        },
    )


def geo_project(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    source: GeoNamesSource,
    index: GeoNamesIndex | None = None,
) -> Project:
    project = Project.open(geo_gw, registry, ref, projects_dir)
    project.attach_sources(queue, {GEONAMES: source}, geonames_index=index)
    return project


def proposed_names(view: ClusterView) -> list[str]:
    return [lv.name for lv in view.cluster.levels if lv.origin == "geonames"]


def test_countries_of_project(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    geo_source: GeoNamesSource,
    geo_index: GeoNamesIndex,
) -> None:
    project = geo_project(
        geo_gw, registry, ref, projects_dir, queue, geo_source, geo_index
    )
    rows = project.countries()
    assert rows[0] == CountryRow(
        iso="CA",
        name="Canada",
        writings=2,
        occurrences=2,
        mode="written",
        downloaded="2026-11-08",
        overrides=0,
    )
    by_name = {r.name: r for r in rows}
    assert set(by_name) == {"Canada", "Royaume-Uni", "Prusse"}
    assert by_name["Royaume-Uni"].iso == "GB"
    assert [r.writings for r in rows] == sorted(
        (r.writings for r in rows), reverse=True
    )


def test_countries_without_index_are_not_downloaded(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
) -> None:
    project = Project.open(geo_gw, registry, ref, projects_dir)
    assert all(r.downloaded is None for r in project.countries())


def test_written_mode_has_no_geonames_proposal(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    geo_source: GeoNamesSource,
) -> None:
    project = geo_project(geo_gw, registry, ref, projects_dir, queue, geo_source)
    assert drain(geo_worker(queue, geo_source)) == 0
    view = view_of(project, WINNIPEG)
    assert proposed_names(view) == []
    assert view.pending_sources == ()
    assert project.effective_mode(view.cluster.id) == ("written", "country")
    assert view.geonames_mode == "written"
    assert view.geonames_mode_origin == "country"


def test_switching_country_enqueues_matches(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    geo_source: GeoNamesSource,
) -> None:
    project = geo_project(geo_gw, registry, ref, projects_dir, queue, geo_source)
    project.set_country_mode("CA", "geonames")
    assert view_of(project, WINNIPEG).pending_sources == (GEONAMES,)
    assert view_of(project, STORRINGTON).pending_sources == ()
    assert drain(geo_worker(queue, geo_source)) >= 1
    view = view_of(project, WINNIPEG)
    assert "Manitoba" in proposed_names(view)
    assert project.countries()[0].mode == "geonames"
    # back to written: proposals are hidden, results stay cached
    project.set_country_mode("CA", "written")
    assert proposed_names(view_of(project, WINNIPEG)) == []
    project.set_country_mode("CA", "geonames")
    assert drain(geo_worker(queue, geo_source)) == 0
    assert "Manitoba" in proposed_names(view_of(project, WINNIPEG))


def test_country_setting_follows_another_project(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
) -> None:
    registry.set_country_mode("CA", "geonames", "other-project")
    project = Project.open(geo_gw, registry, ref, projects_dir)
    assert project.countries()[0].mode == "geonames"
    cluster = view_of(project, WINNIPEG).cluster.id
    assert project.effective_mode(cluster) == ("geonames", "country")


def test_override_flips_one_cluster(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    geo_source: GeoNamesSource,
) -> None:
    project = geo_project(geo_gw, registry, ref, projects_dir, queue, geo_source)
    cluster = view_of(project, WINNIPEG).cluster
    other = view_of(project, STORRINGTON).cluster.id
    project.set_cluster_mode(cluster.id, "geonames")
    assert project.effective_mode(cluster.id) == ("geonames", "override")
    assert project.effective_mode(other) == ("written", "country")
    drain(geo_worker(queue, geo_source))
    assert "Manitoba" in proposed_names(view_of(project, WINNIPEG))
    assert project.countries()[0].overrides == len(cluster.writings)
    # the correction survives a change of the country setting
    project.set_country_mode("CA", "geonames")
    project.set_country_mode("CA", "written")
    assert project.effective_mode(cluster.id) == ("geonames", "override")
    # and a reload / reopen
    project.reload()
    assert project.effective_mode(cluster.id) == ("geonames", "override")
    # a correction opposite to the country setting
    project.set_country_mode("CA", "geonames")
    project.set_cluster_mode(cluster.id, "written")
    assert project.effective_mode(cluster.id) == ("written", "override")
    project.set_cluster_mode(cluster.id, None)
    assert project.effective_mode(cluster.id) == ("geonames", "country")


def test_partial_override_follows_country_and_is_flagged(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
) -> None:
    project = Project.open(geo_gw, registry, ref, projects_dir)
    levels = chain(("Winnipeg", "localite", None), ("Canada", "pays", None))
    validate(registry, [WINNIPEG, WINNIPEG2], levels, project.project_id)
    cluster = view_of(project, WINNIPEG).cluster
    assert set(cluster.writings) == {WINNIPEG, WINNIPEG2}
    registry.set_override([WINNIPEG], GEONAMES, "geonames", project.project_id)
    assert project.effective_mode(cluster.id) == ("written", "partial")
    registry.set_override([WINNIPEG2], GEONAMES, "geonames", project.project_id)
    assert project.effective_mode(cluster.id) == ("geonames", "override")
    registry.set_override([WINNIPEG2], GEONAMES, "written", project.project_id)
    assert project.effective_mode(cluster.id) == ("written", "partial")


def test_override_survives_validation(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
) -> None:
    project = Project.open(geo_gw, registry, ref, projects_dir)
    first = view_of(project, WINNIPEG)
    project.set_cluster_mode(first.cluster.id, "geonames")
    validate_view(registry, first, project.project_id)
    after = view_of(project, WINNIPEG)
    assert after.cluster.id.startswith("place:")
    assert project.effective_mode(after.cluster.id) == ("geonames", "override")


def test_historical_country_has_no_choice(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    geo_source: GeoNamesSource,
) -> None:
    project = geo_project(geo_gw, registry, ref, projects_dir, queue, geo_source)
    prusse = next(r for r in project.countries() if r.name == "Prusse")
    assert (prusse.iso, prusse.mode) == (None, "written")
    with pytest.raises(ValueError):
        project.set_country_mode(prusse.name, "geonames")
    cluster = view_of(project, KONIGSBERG).cluster.id
    with pytest.raises(ValueError):
        project.set_cluster_mode(cluster, "geonames")
    drain(geo_worker(queue, geo_source))
    assert proposed_names(view_of(project, KONIGSBERG)) == []


def test_france_is_not_a_country_row(
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
) -> None:
    project = Project.open(hamlet_gw, registry, ref, projects_dir)
    assert project.countries() == []


def test_refused_geonames_parent_is_reverted(
    geo_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    geo_source: GeoNamesSource,
) -> None:
    project = geo_project(geo_gw, registry, ref, projects_dir, queue, geo_source)
    project.set_country_mode("CA", "geonames")
    drain(geo_worker(queue, geo_source))
    view = view_of(project, WINNIPEG)
    written = [lv.name for lv in view.base_levels]
    manitoba = next(lv for lv in view.cluster.levels if lv.name == "Manitoba")
    assert manitoba.status == "proposed" and manitoba.identifier is not None
    registry.refuse_source_proposal(
        f"writing:{WINNIPEG}", GEONAMES, manitoba.identifier, project.project_id
    )
    view = view_of(project, WINNIPEG)
    levels = view.cluster.levels
    check_chain(levels)
    assert not any(lv.identifier == manitoba.identifier for lv in levels)
    assert any(lv.name == "Manitoba" and lv.status == "validated" for lv in levels)
    assert [lv.rank for lv in levels] == list(range(len(levels)))
    base = {lv.name: lv for lv in view.base_levels}
    assert next(lv for lv in levels if lv.name == "Manitoba") == base["Manitoba"]
    for name in written:  # nothing written is lost
        assert any(name in (lv.name, lv.written) for lv in levels)


def test_unrecognised_last_segments_are_not_countries(
    tmp_path: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    gw = copy_fixture(tmp_path, "lieux_sans_pays.gw")
    project = Project.open(gw, registry, ref, projects_dir)
    assert project.countries() == []


def test_set_country_mode_rejects_unknown_code_and_returns_entry(
    geo_gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = Project.open(geo_gw, registry, ref, projects_dir)
    with pytest.raises(ValueError):
        project.set_country_mode("ZZ", "geonames")
    entry = project.set_country_mode("ca", "geonames")
    assert entry is not None
    registry.undo(entry)
    assert project.countries()[0].mode == "written"
    assert project.set_country_mode("CA", "written") is None


def test_set_cluster_mode_returns_entry_and_needs_an_iso_country(
    geo_gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = Project.open(geo_gw, registry, ref, projects_dir)
    winnipeg = view_of(project, WINNIPEG).cluster.id
    entry = project.set_cluster_mode(winnipeg, "geonames")
    assert entry is not None
    registry.undo(entry)
    assert project.effective_mode(winnipeg) == ("written", "country")
    prusse = view_of(project, KONIGSBERG).cluster.id
    with pytest.raises(ValueError):
        project.set_cluster_mode(prusse, "geonames")
    assert project.set_cluster_mode(prusse, "written") is not None


def test_mixed_country_cluster_is_geonames_only_if_all_countries_are(
    geo_gw: Path, registry: PlaceRegistry, ref: RefData, projects_dir: Path
) -> None:
    project = Project.open(geo_gw, registry, ref, projects_dir)
    levels = chain(("Quelque part", "localite", None))
    validate(registry, [WINNIPEG, STORRINGTON], levels, project.project_id)
    cluster = view_of(project, WINNIPEG).cluster.id
    assert STORRINGTON in view_of(project, WINNIPEG).cluster.writings
    project.set_country_mode("CA", "geonames")
    assert project.effective_mode(cluster) == ("written", "country")
    project.set_country_mode("GB", "geonames")
    assert project.effective_mode(cluster) == ("geonames", "country")


def _proposed(name: str, identifier: str, source: str, written: str | None) -> Level:
    return Level(
        0,
        name,
        written=written,
        type="lieu_dit",
        identifier=identifier,
        source=source,
        origin="dicotopo",
        status="proposed",
    )


def test_revert_refused_is_generic_over_sources() -> None:
    original = chain(("Fictimont", None, None), ("Nord", "departement", "59"))
    typed = _proposed("Fictimont", "P1", DICOTOPO, None)
    inserted = _proposed("Hesdin", "P2", DICOTOPO, None)
    levels = renumber([typed, inserted, original[1]])
    kept = _revert_refused(DICOTOPO, original, levels, frozenset())
    assert kept == levels
    reverted = _revert_refused(
        DICOTOPO, original, levels, frozenset({(DICOTOPO, "P1")})
    )
    assert [(lv.name, lv.status, lv.rank) for lv in reverted] == [
        ("Fictimont", "validated", 0),
        ("Hesdin", "proposed", 1),
        ("Nord", "validated", 2),
    ]
    dropped = _revert_refused(DICOTOPO, original, levels, frozenset({(DICOTOPO, "P2")}))
    assert [lv.name for lv in dropped] == ["Fictimont", "Nord"]
    check_chain(dropped)
    # another source's refusal does not touch it
    other = _revert_refused(DICOTOPO, original, levels, frozenset({(GEONAMES, "P1")}))
    assert other == levels


def test_cached_upper_results_without_asked_name_still_match(
    tmp_path: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    geo_source: GeoNamesSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = tmp_path / "bases" / "anglais.gw"
    gw.parent.mkdir(parents=True)
    gw.write_text(
        "encoding: utf-8\ngwplus\n\n"
        "fam DUPONT Jean 1850 #bp Storrington,_Angleterre,_Royaume-Uni"
        " + MARTIN Marie 1852\n",
        encoding="utf-8",
    )
    search = geo_source.search

    def before_asked(query: LevelQuery) -> list[SourceCandidate]:
        return [dataclasses.replace(c, asked=None) for c in search(query)]

    monkeypatch.setattr(geo_source, "search", before_asked)
    project = geo_project(gw, registry, ref, projects_dir, queue, geo_source)
    project.set_country_mode("GB", "geonames")
    drain(geo_worker(queue, geo_source))
    levels = view_of(project, "Storrington, Angleterre, Royaume-Uni").cluster.levels
    names = [lv.name for lv in levels]
    assert names.count("England") == 1 and "Angleterre" not in names
    assert next(lv for lv in levels if lv.name == "England").written == "Angleterre"


def test_view_names_the_dicotopo_departments_to_download(
    tmp_path: Path,
    hamlet_gw: Path,
    registry: PlaceRegistry,
    ref: RefData,
    projects_dir: Path,
    queue: SourceQueue,
    dicotopo: DicoTopoSource,
) -> None:
    empty = DicoTopoSource(
        DicoTopoIndex(tmp_path / "empty.sqlite"), ref, api_enabled=False
    )
    project = attached(hamlet_gw, registry, ref, projects_dir, queue, empty)
    view = hamlet_view(project)
    assert view.dicotopo_missing == ("62",)
    assert view.pending_sources == ()
    indexed = attached(hamlet_gw, registry, ref, projects_dir, queue, dicotopo)
    assert hamlet_view(indexed).dicotopo_missing == ()
