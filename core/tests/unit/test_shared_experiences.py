"""Tests du regroupement des expériences proches (fixtures synthétiques)."""

import time
from typing import List, Optional, Tuple

import pytest

from geneweb_py.core.date import Date
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.shared_experiences import (
    SHARED_EXPERIENCE_THEMES,
    SharedExperience,
    SharedExperienceIndex,
    SharedReason,
    event_period,
    find_shared_experiences,
    note_words,
    period_gap,
    singularize,
    theme_of,
)


def _parse(text: str) -> Genealogy:
    return GeneWebParser(validate=False).parse_string(text)


def _block(
    person: str,
    tag: str,
    date: str,
    place: Optional[str] = None,
    notes: Tuple[str, ...] = (),
) -> str:
    line = f"#{tag} {date}"
    if place:
        line += f" #p {place}"
    body = "".join(f"note {n}\n" for n in notes)
    return f"pevt {person}\n{line}\n{body}end pevt\n\n"


def _find(text: str, **kwargs: object) -> SharedExperienceIndex:
    return find_shared_experiences(_parse(text), **kwargs)  # type: ignore[arg-type]


def _refs(exp: SharedExperience) -> List[Tuple[str, int]]:
    return [(e.person_id, e.event_index) for e in exp.events]


# --- theme_of -------------------------------------------------------------


def test_theme_of_named_themes() -> None:
    assert theme_of("Deportation") == SHARED_EXPERIENCE_THEMES[0]
    assert theme_of("Deportation").key == "deportation"  # type: ignore[union-attr]
    assert theme_of("Membre_Resistance").key == "resistance"  # type: ignore[union-attr]
    assert theme_of("Voyage_Italie").window == 1  # type: ignore[union-attr]
    assert theme_of("Interne_Camp").key == "internement"  # type: ignore[union-attr]


def test_theme_of_relation() -> None:
    theme = theme_of("Amitie_avec_X")
    assert theme is not None
    assert theme.key == "relation"
    assert theme.label == "Amitié et relations"
    assert theme.window == 3
    assert theme.prefix is None


def test_theme_of_none_and_fallback() -> None:
    assert theme_of("Mariage") is None
    assert theme_of("1914") is None
    assert theme_of("_") is None
    assert theme_of("") is None
    theme = theme_of("Cercle_2")
    assert theme is not None
    assert theme.key == "cercle"
    assert theme.label == "Cercle 2"
    assert theme.window == 1
    assert theme.prefix is None


# --- event_period / period_gap -------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1943", (1943, 1943)),
        ("2/3/1944", (1944, 1944)),
        ("~1943", (1943, 1943)),
        ("?1943", (1943, 1943)),
        ("1942..1944", (1942, 1944)),
        ("1940|1946", (1940, 1946)),
        ("<1940", None),
        (">1940", None),
        ("0(vers la guerre)", None),
    ],
)
def test_event_period(raw: str, expected: Optional[Tuple[int, int]]) -> None:
    assert event_period(Date.parse(raw)) == expected


def test_event_period_none_and_unknown() -> None:
    assert event_period(None) is None
    assert event_period(Date(is_unknown=True)) is None
    assert event_period(Date()) is None


def test_period_gap() -> None:
    assert period_gap((1942, 1944), (1943, 1943)) == 0
    assert period_gap((1940, 1940), (1943, 1943)) == 3
    assert period_gap((1943, 1943), (1940, 1940)) == 3


# --- singularize / note_words ---------------------------------------------


def test_singularize() -> None:
    assert singularize("camps") == "camp"
    assert singularize("convois") == "convoi"
    assert singularize("travaux") == "travau"
    assert singularize("gaz") == "gaz"
    assert singularize("bus") == "bus"
    assert singularize("camp") == "camp"


def test_note_words() -> None:
    words = note_words("Convoi vers le camp de Fictivecamp, avec les déportés")
    assert words == frozenset({"convoi", "camp", "fictivecamp", "deporte"})
    assert note_words("") == frozenset()
    assert note_words("dans la date de l'année") == frozenset()


# --- find_shared_experiences ----------------------------------------------


def test_same_year_same_city() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Villefictive")
        + _block("MARTIN Marie", "Deportation", "1943", "Villefictive")
    )
    assert len(idx.items) == 1
    exp = idx.items[0]
    assert exp.theme == "deportation"
    assert exp.label == "Déportation"
    assert exp.year_min == exp.year_max == 1943
    assert exp.places == ["Villefictive"]
    assert exp.reasons == [SharedReason(kind="same_place", place="Villefictive")]
    assert exp.person_count == 2
    assert exp.event_count == 2
    assert exp.id.startswith("exp-") and len(exp.id) == 14
    assert _refs(exp) == [("DUPONT_Jean_0", 0), ("MARTIN_Marie_0", 0)]
    ev = exp.events[0]
    assert ev.event_type_raw == "Deportation"
    assert (ev.year_start, ev.year_end) == (1943, 1943)
    assert ev.place == "Villefictive"
    assert ev.city == "Villefictive"
    assert idx.undated_total == 0


def test_years_too_far() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Villefictive")
        + _block("MARTIN Marie", "Deportation", "1944", "Villefictive")
    )
    assert idx.items == []


def test_no_city_no_note() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943")
        + _block("MARTIN Marie", "Deportation", "1943")
    )
    assert idx.items == []


def test_unknown_city_question_mark() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "?")
        + _block("MARTIN Marie", "Deportation", "1943", "?")
    )
    assert idx.items == []


def test_rare_word_links_different_cities() -> None:
    idx = _find(
        _block(
            "DUPONT Jean",
            "Deportation",
            "1943",
            "Villefictive",
            ("Parti pour Fictivecamp",),
        )
        + _block(
            "MARTIN Marie",
            "Deportation",
            "1943",
            "Fontfictive",
            ("Arrivée à Fictivecamp en hiver",),
        )
    )
    assert len(idx.items) == 1
    exp = idx.items[0]
    assert exp.reasons == [SharedReason(kind="rare_word", words=("fictivecamp",))]
    assert exp.places == ["Fontfictive", "Villefictive"]


def test_both_reasons_recorded() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Villefictive", ("Fictivecamp",))
        + _block(
            "MARTIN Marie", "Deportation", "1943", "Villefictive", ("Fictivecamp",)
        )
    )
    assert idx.items[0].reasons == [
        SharedReason(kind="rare_word", words=("fictivecamp",)),
        SharedReason(kind="same_place", place="Villefictive"),
    ]


def test_common_word_in_six_notes_does_not_link() -> None:
    text = _block(
        "DUPONT Jean", "Deportation", "1943", "Villefictive", ("Fictivecamp",)
    ) + _block("MARTIN Marie", "Deportation", "1943", "Fontfictive", ("Fictivecamp",))
    for name in ("Paul", "Luc", "Anne", "Zoe"):
        text += _block(f"DURAND {name}", "birt", "1900", notes=("Fictivecamp",))
    idx = _find(text)
    assert idx.items == []


def test_five_notes_is_still_rare() -> None:
    text = _block(
        "DUPONT Jean", "Deportation", "1943", "Villefictive", ("Fictivecamp",)
    ) + _block("MARTIN Marie", "Deportation", "1943", "Fontfictive", ("Fictivecamp",))
    for name in ("Paul", "Luc", "Anne"):
        text += _block(f"DURAND {name}", "birt", "1900", notes=("Fictivecamp",))
    assert len(_find(text).items) == 1


def test_singular_and_plural_link() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Villefictive", ("le camp",))
        + _block("MARTIN Marie", "Deportation", "1943", "Fontfictive", ("les camps",))
    )
    assert len(idx.items) == 1
    assert idx.items[0].reasons == [SharedReason(kind="rare_word", words=("camp",))]


def test_event_city_in_notes_does_not_link() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Villefictive", ("Villefictive",))
        + _block(
            "MARTIN Marie", "Deportation", "1943", "Fontfictive", ("Villefictive",)
        )
    )
    assert idx.items == []


def test_other_place_in_notes_links() -> None:
    idx = _find(
        _block(
            "DUPONT Jean", "Deportation", "1943", "Villefictive", ("vers Montfictif",)
        )
        + _block(
            "MARTIN Marie", "Deportation", "1943", "Fontfictive", ("depuis Montfictif",)
        )
    )
    assert len(idx.items) == 1
    assert idx.items[0].reasons == [
        SharedReason(kind="rare_word", words=("montfictif",))
    ]


def test_theme_words_do_not_link() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Villefictive", ("deporte",))
        + _block("MARTIN Marie", "Deportation", "1943", "Fontfictive", ("déportés",))
    )
    assert idx.items == []


def test_tag_words_do_not_link() -> None:
    idx = _find(
        _block("DUPONT Jean", "Cercle_Lecture", "1943", "Villefictive", ("lecture",))
        + _block("MARTIN Marie", "Cercle_Lecture", "1943", "Fontfictive", ("lecture",))
    )
    assert idx.items == []


def test_same_person_events_do_not_link() -> None:
    text = (
        "pevt DUPONT Jean\n"
        "#Deportation 1943 #p Villefictive\n"
        "#Deportation 1943 #p Villefictive\n"
        "end pevt\n"
    )
    assert _find(text).items == []


def test_exclude_removes_event() -> None:
    text = _block("DUPONT Jean", "Deportation", "1943", "Villefictive") + _block(
        "MARTIN Marie", "Deportation", "1943", "Villefictive"
    )
    assert _find(text, exclude={("MARTIN_Marie_0", 0)}).items == []


def test_ignored_word_removes_event() -> None:
    text = _block("DUPONT Jean", "Voyage_Prive", "1943", "Villefictive") + _block(
        "MARTIN Marie", "Voyage_Prive", "1943", "Villefictive"
    )
    assert len(_find(text).items) == 1
    idx = _find(text, ignored_words={"prive"})
    assert idx.items == []
    assert idx.undated_total == 0


def test_undated_total() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "<1940", "Villefictive")
        + _block("MARTIN Marie", "Deportation", "0(vers_la_guerre)", "Villefictive")
        + _block("DURAND Paul", "Deportation", "1940", "Villefictive")
        + _block("DURAND Luc", "Mariage", "<1940", "Villefictive")
    )
    assert idx.items == []
    assert idx.undated_total == 2


def test_non_other_events_are_ignored() -> None:
    idx = _find(
        _block("DUPONT Jean", "resi", "1943", "Villefictive")
        + _block("MARTIN Marie", "resi", "1943", "Villefictive")
    )
    assert idx.items == []


def test_relation_window_three_years() -> None:
    idx = _find(
        _block("DUPONT Jean", "Amitie_avec_Marie", "1940", "Villefictive")
        + _block("MARTIN Marie", "Correspondance", "1943", "Villefictive")
    )
    assert len(idx.items) == 1
    assert idx.items[0].theme == "relation"


def test_range_overlap_links() -> None:
    idx = _find(
        _block("DUPONT Jean", "Resistance", "1942..1944", "Villefictive")
        + _block("MARTIN Marie", "Resistance", "1943", "Villefictive")
    )
    assert len(idx.items) == 1
    assert (idx.items[0].year_min, idx.items[0].year_max) == (1942, 1944)


def _chain(tag: str) -> str:
    return "".join(
        _block(person, tag, year, "Villefictive")
        for person, year in (
            ("DUPONT Jean", "1940"),
            ("MARTIN Marie", "1941"),
            ("DURAND Paul", "1942"),
            ("LEROY Anne", "1943"),
        )
    )


def test_chain_split_window_0() -> None:
    assert _find(_chain("Deportation")).items == []


def test_chain_split_window_1() -> None:
    idx = _find(_chain("Voyage"))
    assert len(idx.items) == 1
    assert _refs(idx.items[0]) == [
        ("DUPONT_Jean_0", 0),
        ("MARTIN_Marie_0", 0),
        ("DURAND_Paul_0", 0),
    ]
    assert (idx.items[0].year_min, idx.items[0].year_max) == (1940, 1942)


def test_order_independent() -> None:
    blocks = [
        _block("DUPONT Jean", "Voyage", "1940", "Villefictive"),
        _block("MARTIN Marie", "Voyage", "1941", "Villefictive"),
        _block("DURAND Paul", "Voyage", "1942", "Fontfictive", ("Montfictif",)),
        _block("LEROY Anne", "Voyage", "1942", "Fontfictive", ("Montfictif",)),
        _block("DUPONT Luc", "Deportation", "1943", "Villefictive"),
        _block("MARTIN Zoe", "Deportation", "1943", "Villefictive"),
        _block("DURAND Anne", "Cercle_2", "1950", "Villefictive"),
        _block("LEROY Paul", "Cercle_3", "1950", "Villefictive"),
    ]
    forward = _find("".join(blocks))
    backward = _find("".join(reversed(blocks)))

    def summary(idx: SharedExperienceIndex) -> List[object]:
        return [(e.id, e.theme, e.label, _refs(e), e.reasons) for e in idx.items]

    assert summary(forward) == summary(backward)
    assert [e.theme for e in forward.items] == [
        "cercle",
        "deportation",
        "voyage",
        "voyage",
    ]


def test_large_theme_is_fast() -> None:
    text = "".join(
        _block(f"DUPONT Jean.{i}", "Voyage", "1943", f"Villefictive{chr(65 + i % 30)}")
        for i in range(1500)
    )
    genealogy = _parse(text)
    start = time.perf_counter()
    idx = find_shared_experiences(genealogy)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0
    assert len(idx.items) == 30
    assert all(e.person_count == 50 for e in idx.items)


def test_numeric_and_empty_tags_are_ignored() -> None:
    idx = _find(
        _block("DUPONT Jean", "1914", "1914", "Villefictive")
        + _block("MARTIN Marie", "1914", "1914", "Villefictive")
        + _block("DURAND Paul", "_", "1914", "Villefictive")
        + _block("LEROY Anne", "_", "1914", "Villefictive")
    )
    assert idx.items == []
    assert idx.undated_total == 0


def test_notes_with_only_stopwords_city_and_short_words() -> None:
    notes = ("dans Villefictive avec eux en mai, date et année",)
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Villefictive", notes)
        + _block("MARTIN Marie", "Deportation", "1943", "Fontfictive", notes)
    )
    assert idx.items == []


def _root(parent: dict, k: int) -> int:
    while parent[k] != k:
        k = parent[k]
    return k


def _reference_components(genealogy: Genealogy) -> List[Tuple[str, List[str]]]:
    """Calcul naïf par paires (§ 4.1), pour vérifier le balayage du module."""
    from geneweb_py.core.place import place_city

    by_theme: dict = {}
    for pid, person in genealogy.persons.items():
        for idx, ev in enumerate(person.events):
            theme = theme_of(ev.event_type_raw or "")
            period = event_period(ev.date)
            if theme is None or period is None:
                continue
            city = (place_city(ev.place) or "").strip().lower()
            by_theme.setdefault(theme.key, (theme, []))[1].append(
                (period[0], period[1], pid, idx, "" if city == "?" else city)
            )
    result = []
    for key, (theme, events) in sorted(by_theme.items()):
        events.sort()
        span = max(1, 2 * theme.window)
        placed = [False] * len(events)
        for i in range(len(events)):
            if placed[i]:
                continue
            chunk = [i]
            placed[i] = True
            limit = max(events[i][0] + span, events[i][1])
            for j in range(i + 1, len(events)):
                if not placed[j] and events[j][0] <= limit:
                    placed[j] = True
                    chunk.append(j)
            parent = {k: k for k in chunk}

            for x, a in enumerate(chunk):
                for b in chunk[x + 1 :]:
                    ea, eb = events[a], events[b]
                    gap = period_gap((ea[0], ea[1]), (eb[0], eb[1]))
                    if (
                        ea[2] != eb[2]
                        and gap <= theme.window
                        and ea[4]
                        and ea[4] == eb[4]
                    ):
                        parent[_root(parent, b)] = _root(parent, a)
            groups: dict = {}
            for k in chunk:
                groups.setdefault(_root(parent, k), []).append(k)
            for members in groups.values():
                if len({events[k][2] for k in members}) >= 2:
                    result.append(
                        (key, sorted(f"{events[k][2]}:{events[k][3]}" for k in members))
                    )
    return sorted(result)


@pytest.mark.parametrize("seed", range(20))
def test_same_place_sweep_matches_pairwise(seed: int) -> None:
    import random

    rng = random.Random(seed)
    names = ["DUPONT Jean", "MARTIN Marie", "DURAND Paul", "LEROY Anne", "PETIT Luc"]
    tags = ["Deportation", "Voyage", "Amitie", "Cercle"]
    cities = ["Villefictive", "Fontfictive", "?", ""]
    text = ""
    for name in names:
        lines = []
        for _ in range(rng.randint(1, 12)):
            start = rng.randint(1940, 1950)
            date = str(start)
            if rng.random() < 0.3:
                date = f"{start}..{start + rng.randint(1, 4)}"
            city = rng.choice(cities)
            line = f"#{rng.choice(tags)} {date}"
            if city:
                line += f" #p {city}"
            lines.append(line)
        text += f"pevt {name}\n" + "\n".join(lines) + "\nend pevt\n\n"
    genealogy = _parse(text)
    got = sorted(
        (e.theme, sorted(f"{r[0]}:{r[1]}" for r in _refs(e)))
        for e in find_shared_experiences(genealogy).items
    )
    assert got == _reference_components(genealogy)


def test_rare_word_same_person_does_not_link() -> None:
    text = (
        "pevt DUPONT Jean\n"
        "#Deportation 1943 #p Villefictive\nnote Fictivecamp\n"
        "#Deportation 1943 #p Fontfictive\nnote Fictivecamp\n"
        "end pevt\n"
    )
    assert _find(text).items == []


def test_rare_word_too_far_in_same_slice() -> None:
    idx = _find(
        _block("DUPONT Jean", "Voyage", "1940", "Villefictive", ("Montfictif",))
        + _block("MARTIN Marie", "Voyage", "1942", "Fontfictive", ("Montfictif",))
    )
    assert idx.items == []


# --- revue finale : tranches par début, clés de ville, lieux ---------------


def test_identical_ranges_are_linked() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1942..1944", "Villefictive")
        + _block("MARTIN Marie", "Deportation", "1942..1944", "Villefictive")
    )
    assert len(idx.items) == 1


def test_alternative_dates_link_with_inner_year() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1940|1946", "Villefictive")
        + _block("MARTIN Marie", "Deportation", "1943", "Villefictive")
    )
    assert len(idx.items) == 1


def test_wide_range_links_with_inner_year() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1941..1943", "Villefictive")
        + _block("MARTIN Marie", "Deportation", "1943", "Villefictive")
    )
    assert len(idx.items) == 1


def test_long_range_elsewhere_does_not_merge_experiences() -> None:
    text = "".join(
        _block(name, "Voyage", year, "Villefictive")
        for name, year in [
            ("DUPONT Jean", "1940"),
            ("MARTIN Marie", "1941"),
            ("DURAND Paul", "1942"),
            ("LEROY Anne", "1943"),
            ("PETIT Luc", "1944"),
            ("BERNARD Zoe", "1945"),
        ]
    )
    text += _block("ROUX Leo", "Voyage", "1940..1950", "Montfictif")
    idx = _find(text)
    assert [(e.year_min, e.year_max) for e in idx.items] == [(1940, 1942), (1943, 1945)]


def test_chain_of_overlapping_ranges_stays_bounded() -> None:
    text = "".join(
        _block(
            f"FICTIF{c} Jean",
            "Deportation",
            f"{1900 + 2 * i}..{1902 + 2 * i}",
            "Villefictive",
        )
        for i, c in enumerate("ABCDEFGHIJ")
    )
    idx = _find(text)
    assert len(idx.items) > 1
    assert all(e.year_max - e.year_min <= 4 for e in idx.items)


def test_city_key_ignores_hyphen_and_underscore() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Saint-Fictif")
        + _block("MARTIN Marie", "Deportation", "1943", "Saint_Fictif")
    )
    assert len(idx.items) == 1
    assert idx.items[0].places == ["Saint-Fictif"]


def test_places_deduplicated_by_city_key() -> None:
    idx = _find(
        _block("DUPONT Jean", "Deportation", "1943", "Évreux-Fictif")
        + _block("MARTIN Marie", "Deportation", "1943", "evreux-fictif")
    )
    assert len(idx.items) == 1
    assert len(idx.items[0].places) == 1


def test_theme_of_skips_empty_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from geneweb_py.core import shared_experiences as se

    empty = se.Theme(key="vide", label="Vide", window=1, prefix="")
    monkeypatch.setattr(
        se, "SHARED_EXPERIENCE_THEMES", (empty, *se.SHARED_EXPERIENCE_THEMES)
    )
    theme = se.theme_of("Deportation")
    assert theme is not None and theme.key != "vide"
