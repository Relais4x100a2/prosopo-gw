"""Tests du filtre de l'oracle (fixtures synthétiques uniquement)."""

import re

from oracle.filter import filter_lines


def test_filter_drops_wnote_and_repeated_comm():
    lines = ["fam DUPONT Jean + MARTIN Anne", "comm a", "comm b", "wnote x", "end"]
    out, counts = filter_lines(lines, [re.compile(r"^wnote ")])
    assert out == ["fam DUPONT Jean + MARTIN Anne", "comm a", "end"]
    assert counts["comm répété"] == 1
    assert counts["^wnote "] == 1


def test_filter_keeps_fevt_block():
    lines = ["fam DUPONT Jean + MARTIN Anne", "fevt", "#marr 1900 #p Paris", "end fevt"]
    out, _ = filter_lines(lines, [])
    assert out == lines
