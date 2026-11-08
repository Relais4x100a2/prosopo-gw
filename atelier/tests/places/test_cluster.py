import csv
import gzip
import random
import time
from pathlib import Path

import pytest
from geneweb_py import GeneWebParser
from geneweb_py.formats.tables import build_base_tables

from prosopo_gw_atelier.places.cluster import (
    SIMILARITY_THRESHOLD,
    Cluster,
    KnownPlace,
    _length_range,
    build_clusters,
    similar,
)
from prosopo_gw_atelier.places.collect import collect_writings
from prosopo_gw_atelier.places.decompose import decompose
from prosopo_gw_atelier.places.levels import french_view, rule_levels
from prosopo_gw_atelier.places.model import Decomposition
from prosopo_gw_atelier.refdata import RefData, load_refdata, normalize
from prosopo_gw_atelier.refdata.loader import DEFAULT_DATA_DIR

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MINI = FIXTURES / "refdata_mini"
FIXTURE_GW = FIXTURES / "lieux_varies.gw"

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


@pytest.fixture(scope="module")
def fixture_decompositions(ref: RefData) -> dict[str, Decomposition]:
    tables = build_base_tables(GeneWebParser().parse_file(str(FIXTURE_GW)))
    return {text: decompose(text, ref) for text in collect_writings(tables)}


def decompose_all(writings: list[str], ref: RefData) -> dict[str, Decomposition]:
    return {text: decompose(text, ref) for text in writings}


def by_id(clusters: list[Cluster]) -> dict[str, Cluster]:
    return {cluster.id: cluster for cluster in clusters}


def _clusters(writings: list[str], ref: RefData) -> list[Cluster]:
    return build_clusters({w: decompose(w, ref) for w in writings}, ref, {})


def _by_id(clusters: list[Cluster], cluster_id: str) -> Cluster:
    (found,) = [c for c in clusters if c.id == cluster_id]
    return found


def cluster_of(clusters: list[Cluster], writing: str) -> Cluster:
    (found,) = [c for c in clusters if writing in c.writings]
    return found


def test_roubaix_writings_form_one_high_cluster(
    fixture_decompositions: dict[str, Decomposition], ref: RefData
) -> None:
    clusters = by_id(build_clusters(fixture_decompositions, ref, {}))
    roubaix = clusters["insee:59512"]
    assert roubaix.writings == ROUBAIX_WRITINGS
    assert roubaix.confidence == "high"
    assert roubaix.anchor_place_id is None
    assert french_view(roubaix.levels, roubaix.postal_code) == {
        "commune": "Roubaix",
        "department": "59",
        "region": "Hauts-de-France",
        "insee_code": "59512",
        "postal_code": "59100",
        "country": "France",
    }


def test_every_writing_is_in_exactly_one_cluster(
    fixture_decompositions: dict[str, Decomposition], ref: RefData
) -> None:
    clusters = build_clusters(fixture_decompositions, ref, {})
    placed = [w for c in clusters for w in c.writings]
    assert sorted(placed) == sorted(fixture_decompositions)


def test_fixture_clusters(
    fixture_decompositions: dict[str, Decomposition], ref: RefData
) -> None:
    clusters = by_id(build_clusters(fixture_decompositions, ref, {}))
    assert clusters["insee:59350"].writings == [
        "Lille",
        "Lille, France",
        "Lille, Nord, France",
    ]
    assert clusters["historique:59355|lomme"].writings == ["Lomme"]
    assert clusters["insee:59350"].confidence == "high"
    assert clusters["insee:62765"].confidence == "high"  # St-Omer (62)
    assert clusters["insee:69123"].confidence == "medium"  # Lyon, bare name
    assert clusters["name:merville"].confidence == "low"
    assert clusters["name:en mer"].confidence == "low"


def test_homonyms_stay_apart(ref: RefData) -> None:
    decompositions = decompose_all(
        ["Merville", "MERVILLE", "Merville, Nord", "Merville (31)"], ref
    )
    clusters = by_id(build_clusters(decompositions, ref, {}))
    assert set(clusters) == {"name:merville", "insee:59400", "insee:31341"}
    assert clusters["name:merville"].writings == ["MERVILLE", "Merville"]
    assert clusters["name:merville"].confidence == "low"
    assert clusters["insee:59400"].writings == ["Merville, Nord"]
    assert clusters["insee:31341"].writings == ["Merville (31)"]


def test_two_bare_homonym_writings_are_two_low_clusters(ref: RefData) -> None:
    # Both Merville communes, written without department: neither may be merged
    # into a resolved cluster, nor with an unresolved look-alike.
    decompositions = decompose_all(["Merville", "Merville, France", "Mervile"], ref)
    clusters = by_id(build_clusters(decompositions, ref, {}))
    assert clusters["name:merville"].writings == ["Merville", "Merville, France"]
    assert clusters["name:merville"].confidence == "low"
    assert clusters["name:mervile"].writings == ["Mervile"]
    assert clusters["name:mervile"].confidence == "low"


def test_new_writing_is_anchored_to_a_known_place(ref: RefData) -> None:
    known = {"place-7": KnownPlace("place-7", "59512", "roubaix")}
    decompositions = decompose_all(["Roubaix (Nord)"], ref)
    clusters = build_clusters(decompositions, ref, known)
    assert clusters == [
        Cluster(
            id="insee:59512",
            writings=["Roubaix (Nord)"],
            levels=rule_levels(decompositions["Roubaix (Nord)"], ref),
            postal_code=None,
            confidence="high",
            anchor_place_id="place-7",
        )
    ]
    assert french_view(clusters[0].levels, clusters[0].postal_code) == {
        "commune": "Roubaix",
        "department": "59",
        "region": "Hauts-de-France",
        "insee_code": "59512",
        "country": "France",
    }


def test_unresolved_writing_is_anchored_by_name_key(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", None, "en mer")}
    clusters = build_clusters(decompose_all(["En mer"], ref), ref, known)
    assert clusters[0].anchor_place_id == "p1"


def test_name_key_does_not_anchor_across_insee_codes(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", "31341", "merville")}
    clusters = by_id(build_clusters(decompose_all(["Merville, Nord"], ref), ref, known))
    assert clusters["insee:59400"].anchor_place_id is None


def test_name_key_does_not_anchor_across_departments(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", None, "merville", "31")}
    clusters = by_id(build_clusters(decompose_all(["Merville, Nord"], ref), ref, known))
    assert clusters["insee:59400"].anchor_place_id is None


@pytest.mark.parametrize("department", ["59", "Nord", None])
def test_name_key_anchors_in_the_same_or_an_unknown_department(
    ref: RefData, department: str | None
) -> None:
    known = {"p1": KnownPlace("p1", None, "merville", department)}
    clusters = by_id(build_clusters(decompose_all(["Merville, Nord"], ref), ref, known))
    assert clusters["insee:59400"].anchor_place_id == "p1"


def test_unresolved_name_does_not_anchor_across_departments(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", None, normalize("Saint-Inconnu"), "62")}
    clusters = build_clusters(decompose_all(["Saint-Inconnu, Nord"], ref), ref, known)
    assert [c.anchor_place_id for c in clusters] == [None]
    elsewhere = {"p1": KnownPlace("p1", None, normalize("Saint-Inconnu"), "59")}
    clusters = build_clusters(
        decompose_all(["Saint-Inconnu, Nord"], ref), ref, elsewhere
    )
    assert [c.anchor_place_id for c in clusters] == ["p1"]


def test_no_anchor_by_similarity_alone(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", None, "en mer")}
    clusters = build_clusters(decompose_all(["En mere"], ref), ref, known)
    assert clusters[0].anchor_place_id is None


def test_typo_merges_into_resolved_cluster_at_most_medium(ref: RefData) -> None:
    clusters = build_clusters(decompose_all(["Lile", "Lille"], ref), ref, {})
    assert len(clusters) == 1
    assert clusters[0].id == "insee:59350"
    assert clusters[0].writings == ["Lile", "Lille"]
    assert clusters[0].confidence == "medium"


def test_similarity_merge_caps_a_high_cluster(ref: RefData) -> None:
    clusters = build_clusters(decompose_all(["Lile", "Lille, Nord"], ref), ref, {})
    assert [c.id for c in clusters] == ["insee:59350"]
    assert clusters[0].confidence == "medium"


def test_threshold_separates_typo_from_other_name() -> None:
    from difflib import SequenceMatcher

    assert SequenceMatcher(None, "lile", "lille").ratio() >= SIMILARITY_THRESHOLD
    assert SequenceMatcher(None, "lille", "lillers").ratio() < SIMILARITY_THRESHOLD


def test_similar_uses_the_threshold_and_the_first_letter() -> None:
    assert similar("lile", "lille") and similar("winipeg", "winnipeg")
    assert not similar("lille", "lillers")
    assert not similar("ille", "lille")  # another first letter: another block
    assert not similar("", "")


@pytest.mark.parametrize("size", [17, 23, 34, 46, 68])
def test_length_range_is_exact_at_the_boundary(size: int) -> None:
    lengths = _length_range(size)
    for other in range(1, 3 * size):
        reachable = 2 * min(size, other) * 20 >= 17 * (size + other)
        assert (other in lengths) == reachable, (size, other)


def test_exact_threshold_ratio_merges(ref: RefData) -> None:
    # 17 letters inside 23: ratio 2 * 17 / 40 == 0.85 exactly.
    short, long = "Bourgvalemontagne", "Bourgvalemontagnezqwkjy"
    assert len(short) == 17 and len(long) == 23
    clusters = build_clusters(decompose_all([short, long], ref), ref, {})
    assert [c.writings for c in clusters] == [[short, long]]


def test_close_but_distinct_names_do_not_merge(ref: RefData) -> None:
    # Same gap as Lille / Lillers, on two names absent from refdata_mini.
    clusters = by_id(build_clusters(decompose_all(["Lillars", "Lilla"], ref), ref, {}))
    assert set(clusters) == {"name:lillars", "name:lilla"}


def test_unresolved_typos_merge_together_as_low(ref: RefData) -> None:
    clusters = build_clusters(decompose_all(["Bourgvalle", "Bourgvale"], ref), ref, {})
    assert len(clusters) == 1
    assert clusters[0].id == "name:bourgvale"
    assert clusters[0].writings == ["Bourgvale", "Bourgvalle"]
    assert clusters[0].confidence == "low"
    assert [level.name for level in clusters[0].levels] == ["Bourgvale"]


def test_similarity_respects_blocks(ref: RefData) -> None:
    # Different first letter: no merge even if the strings are close.
    clusters = by_id(build_clusters(decompose_all(["Kille", "Lille"], ref), ref, {}))
    assert set(clusters) == {"name:kille", "insee:59350"}
    # Known, different department: no merge.
    clusters = by_id(
        build_clusters(decompose_all(["Lile (69)", "Lille"], ref), ref, {})
    )
    assert set(clusters) == {"name:lile|69", "insee:59350"}
    # Same department: merge.
    clusters = by_id(
        build_clusters(decompose_all(["Lile (59)", "Lille"], ref), ref, {})
    )
    assert set(clusters) == {"insee:59350"}


def test_unresolved_key_includes_department(ref: RefData) -> None:
    clusters = by_id(
        build_clusters(decompose_all(["Bourgvale, Nord", "Bourgvale"], ref), ref, {})
    )
    # Same name, department unknown on one side: merged by similarity (ratio 1).
    assert set(clusters) == {"name:bourgvale"}
    assert clusters["name:bourgvale"].writings == ["Bourgvale", "Bourgvale, Nord"]


def test_confidence_from_elements(ref: RefData) -> None:
    cases = {
        "59100 Roubaix": "high",  # postal code
        "59512": "high",  # INSEE code
        "Roubaix, Nord": "high",  # name + agreeing department
        "Roubaix": "medium",  # unique name
        "Roubaix, Nord-Pas-de-Calais": "medium",  # region is not checked
        "Roubaix (69)": "medium",  # disagreeing department
        "Lomme": "medium",  # unique former name
    }
    for writing, expected in cases.items():
        (cluster,) = build_clusters(decompose_all([writing], ref), ref, {})
        assert cluster.confidence == expected, writing


def test_deterministic_regardless_of_insertion_order(
    fixture_decompositions: dict[str, Decomposition], ref: RefData
) -> None:
    extra = decompose_all(["Lile", "Bourgvale", "Bourgvalle", "MERVILLE"], ref)
    items = list({**fixture_decompositions, **extra}.items())
    expected = build_clusters(dict(items), ref, {})
    assert [c.id for c in expected] == sorted(c.id for c in expected)
    for seed in range(5):
        shuffled = items[:]
        random.Random(seed).shuffle(shuffled)
        assert build_clusters(dict(shuffled), ref, {}) == expected


def _real_communes() -> list[tuple[str, str, str]]:
    with gzip.open(DEFAULT_DATA_DIR / "communes.csv.gz", "rt", encoding="utf-8") as f:
        return [
            (row["insee"], row["nom"], row["departement"])
            for row in csv.DictReader(f, delimiter=";")
        ]


def test_clusters_large_input() -> None:
    ref = load_refdata()
    rng = random.Random(20261107)
    communes = rng.sample(_real_communes(), 6000)
    letters = "abcdefghijklmnopqrstuvwxyz"
    writings: set[str] = set()
    while len(writings) < 20_000:
        insee, name, department = rng.choice(communes)
        variant = rng.randrange(6)
        if variant == 0:
            writings.add(name)
        elif variant == 1:
            writings.add(f"{name.upper()}, {department}")
        elif variant == 2:
            writings.add(f"{name} ({department})")
        elif variant == 3:
            writings.add(insee)
        else:  # typo or random suffix: mostly unresolved
            writings.add(f"{name}{rng.choice(letters)}{rng.choice(letters)}")
    decompositions = {text: decompose(text, ref) for text in sorted(writings)}

    start = time.perf_counter()
    clusters = build_clusters(decompositions, ref, {})
    elapsed = time.perf_counter() - start

    assert elapsed < 10, f"build_clusters took {elapsed:.1f} s"
    placed = [w for c in clusters for w in c.writings]
    assert len(placed) == len(writings)
    assert set(placed) == writings
    assert len({c.id for c in clusters}) == len(clusters)
    # The similarity path ran: unresolved writings joined resolved clusters.
    merged_in = [
        w
        for c in clusters
        if c.id.startswith("insee:")
        for w in c.writings
        if decompositions[w].insee is None
    ]
    assert merged_in
    print(f"build_clusters: {len(writings)} writings in {elapsed:.2f} s")


def test_normalized_keys_used_for_ids(ref: RefData) -> None:
    clusters = build_clusters(decompose_all(["Saint-Bourgvale"], ref), ref, {})
    assert clusters[0].id == f"name:{normalize('St Bourgvale')}"


def test_marconne_hesdin_and_hesdin_la_foret_are_three_clusters(ref: RefData) -> None:
    clusters = _clusters(["Marconne", "Hesdin, Pas-de-Calais", "Hesdin-la-Forêt"], ref)
    assert sorted(c.id for c in clusters) == [
        "historique:62447|hesdin",
        "historique:62549|marconne",
        "insee:62447",
    ]
    marconne = _by_id(clusters, "historique:62549|marconne")
    assert [lv.name for lv in marconne.levels][:2] == ["Marconne", "Hesdin-la-Forêt"]


def test_lomme_is_not_merged_into_lille(ref: RefData) -> None:
    ids = {c.id for c in _clusters(["Lomme", "Lille"], ref)}
    assert ids == {"historique:59355|lomme", "insee:59350"}


def test_foreign_writings_without_contradiction_merge(ref: RefData) -> None:
    [cluster] = _clusters(
        [
            "Storrington, Royaume-Uni",
            "Storrington, , East Sussex, England, Royaume-Uni",
        ],
        ref,
    )
    assert [lv.name for lv in cluster.levels] == [
        "Storrington",
        "East Sussex",
        "England",
        "Royaume-Uni",
    ]


def test_contradicting_levels_split_with_low_confidence(ref: RefData) -> None:
    clusters = _clusters(["Storrington, East Sussex", "Storrington, West Sussex"], ref)
    assert len(clusters) == 2
    assert {c.confidence for c in clusters} == {"low"}
    assert sorted(c.id for c in clusters) == ["name:storrington", "name:storrington~2"]


def test_ambiguous_former_name_is_medium_with_alternative(ref: RefData) -> None:
    [cluster] = _clusters(["Sainte-Austreberthe, Seine-Maritime"], ref)
    assert cluster.id == "insee:76566" and cluster.confidence == "medium"
    assert cluster.alternatives[0][0].name == "Sainte-Austreberthe"
    assert cluster.alternatives[0][1].name == "Hesdin-la-Forêt"


def test_historical_anchor(ref: RefData) -> None:
    known = {
        "p1": KnownPlace("p1", None, "marconne", "62", "62549|marconne"),
        "p2": KnownPlace("p2", "62447", "hesdin la foret", "62"),
    }
    clusters = build_clusters(
        {w: decompose(w, ref) for w in ["Marconne", "Hesdin-la-Forêt"]}, ref, known
    )
    assert {c.id: c.anchor_place_id for c in clusters} == {
        "historique:62549|marconne": "p1",
        "insee:62447": "p2",
    }


def test_postal_code_proposal(ref: RefData) -> None:
    [cluster] = _clusters(["Roubaix 59100", "Roubaix"], ref)
    assert cluster.postal_code == "59100"


def test_finer_level_writing_is_a_distinct_cluster(ref: RefData) -> None:
    clusters = _clusters(["Lille", "Lille, Nord", "Lile", "Wazemmes, Lille"], ref)
    assert sorted(c.id for c in clusters) == ["insee:59350", "insee:59350|wazemmes"]
    lille = _by_id(clusters, "insee:59350")
    assert lille.writings == ["Lile", "Lille", "Lille, Nord"]
    assert (lille.levels[0].name, lille.levels[0].type) == ("Lille", "commune")
    wazemmes = _by_id(clusters, "insee:59350|wazemmes")
    assert wazemmes.writings == ["Wazemmes, Lille"]
    assert (wazemmes.levels[0].name, wazemmes.levels[0].type) == ("Wazemmes", None)
    assert wazemmes.levels[1].name == "Lille"


def test_finer_level_under_a_former_commune_is_distinct(ref: RefData) -> None:
    clusters = _clusters(["Lomme", "Canteleu, Lomme"], ref)
    assert sorted(c.id for c in clusters) == [
        "historique:59355|lomme",
        "historique:59355|lomme|canteleu",
    ]


def test_finer_level_does_not_take_a_similarity_merge(ref: RefData) -> None:
    clusters = _clusters(["Wazemmes, Lille", "Lillle"], ref)
    assert cluster_of(clusters, "Lillle").id != "insee:59350|wazemmes"


def test_commune_and_finer_places_do_not_anchor_on_each_other(ref: RefData) -> None:
    known = {
        "p1": KnownPlace("p1", "59350", "lille", "59", finer="wazemmes"),
        "p2": KnownPlace("p2", "59350", "lille", "59"),
    }
    clusters = build_clusters(
        decompose_all(["Lille", "Wazemmes, Lille", "Fives, Lille"], ref), ref, known
    )
    assert {c.id: c.anchor_place_id for c in clusters} == {
        "insee:59350": "p2",
        "insee:59350|fives": None,
        "insee:59350|wazemmes": "p1",
    }


def test_finer_place_alone_does_not_anchor_the_commune(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", "59350", "lille", "59", finer="wazemmes")}
    [cluster] = build_clusters(decompose_all(["Lille"], ref), ref, known)
    assert cluster.anchor_place_id is None
