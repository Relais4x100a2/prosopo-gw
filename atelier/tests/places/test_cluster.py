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
)
from prosopo_gw_atelier.places.collect import collect_writings
from prosopo_gw_atelier.places.decompose import decompose
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
    assert roubaix.proposal == {
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
        "Lomme",
    ]
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
    clusters = build_clusters(decompose_all(["Roubaix (Nord)"], ref), ref, known)
    assert clusters == [
        Cluster(
            id="insee:59512",
            writings=["Roubaix (Nord)"],
            proposal={
                "commune": "Roubaix",
                "department": "59",
                "region": "Hauts-de-France",
                "insee_code": "59512",
            },
            confidence="high",
            anchor_place_id="place-7",
        )
    ]


def test_unresolved_writing_is_anchored_by_name_key(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", None, "en mer")}
    clusters = build_clusters(decompose_all(["En mer"], ref), ref, known)
    assert clusters[0].anchor_place_id == "p1"


def test_name_key_does_not_anchor_across_insee_codes(ref: RefData) -> None:
    known = {"p1": KnownPlace("p1", "31341", "merville")}
    clusters = by_id(build_clusters(decompose_all(["Merville, Nord"], ref), ref, known))
    assert clusters["insee:59400"].anchor_place_id is None


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
    assert clusters[0].proposal == {"commune": "Bourgvale"}


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
