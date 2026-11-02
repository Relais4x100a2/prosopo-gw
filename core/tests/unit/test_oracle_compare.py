"""Tests du comparateur d'oracle (fixtures synthétiques uniquement)."""

from pathlib import Path

from oracle.compare import FieldStat, compare_families, load, mask, norm, render_table

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
