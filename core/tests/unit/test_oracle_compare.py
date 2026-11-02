"""Tests du comparateur d'oracle (fixtures synthétiques uniquement)."""

from pathlib import Path

from oracle.compare import (
    FieldStat,
    compare_events,
    compare_families,
    compare_persons,
    load,
    mask,
    naive_tag_counts,
    norm,
    render_table,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _pair(stream: bool = False):
    return (
        load(str(FIX / "oracle_source.gw"), stream),
        load(str(FIX / "oracle_rt.gw"), stream),
    )


def test_mask_hides_letters_and_digits():
    assert mask("Paris 1900, rue Émile") == "aaaaa 9999, aaa aaaaa"


def test_norm_decodes_underscore_and_escape():
    assert norm("Saint_Denis") == "Saint Denis"
    assert norm(r"rue\_haute") == "rue_haute"
    assert norm(None) == ""


def test_compare_families_counts_known_gap():
    got, ref = _pair()
    stats: dict[str, FieldStat] = {}
    assert compare_families(got, ref, stats) == 0
    assert stats["fam.marriage_date"].present == 3
    assert stats["fam.marriage_date"].equal == 3
    # source du mariage retirée volontairement dans rt sur la 2e famille
    assert stats["fam.marriage_source"].present == 1


def test_render_table_has_one_row_per_field():
    s = {"fam.marriage_date": FieldStat()}
    s["fam.marriage_date"].add("1900", "1900")
    out = render_table(s, {"familles": 0})
    assert "| fam.marriage_date | 1 | 1 | 0 | 0 | 100.0 % |" in out


def _run(src: Path, rt: Path, stream: bool):
    got, ref = load(str(src), stream), load(str(rt), stream)
    stats: dict[str, FieldStat] = {}
    unmatched = {
        "familles": compare_families(got, ref, stats),
        "personnes": compare_persons(got, ref, stats),
        "événements": compare_events(got, ref, stats),
    }
    return stats, unmatched


def test_compare_persons_counts_known_gap():
    got, ref = _pair()
    stats: dict[str, FieldStat] = {}
    assert compare_persons(got, ref, stats) == 0
    bp = stats["pers.birth_place"]
    assert bp.present >= 2
    assert bp.present - bp.equal == 1  # un lieu modifié volontairement dans rt


def test_compare_unmatched_person_counted(tmp_path):
    src = (FIX / "oracle_source.gw").read_text(encoding="utf-8")
    plus = tmp_path / "rt_plus.gw"
    plus.write_text(src + "\nfam DURAND Marc + ROUX Lise\n", encoding="utf-8")
    got, ref = load(str(FIX / "oracle_source.gw"), False), load(str(plus), False)
    assert compare_persons(got, ref, {}) == 2


def test_compare_events_pairs_pevt_by_type_and_date():
    got, ref = _pair()
    stats: dict[str, FieldStat] = {}
    # gwu synthétise 6 naissances (pevt) et 3 mariages (fevt) que le parser ne crée pas encore
    # (règle de réconciliation de la phase 1) : valeur de départ, à ramener à 0.
    assert compare_events(got, ref, stats) == 9
    assert stats["pevt.place"].present >= 1


def test_compare_both_modes_same_table():
    a = render_table(*_run(FIX / "oracle_source.gw", FIX / "oracle_rt.gw", False))
    b = render_table(*_run(FIX / "oracle_source.gw", FIX / "oracle_rt.gw", True))
    assert a == b


def test_naive_tag_counts():
    counts = naive_tag_counts("- h Pierre #bp Paris #src x\nwit m: DUPONT Luc\n")
    assert counts["#bp"] == 1
    assert counts["#src"] == 1
    assert counts["wit"] == 1
