from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest

from prosopo_gw_atelier.sources.dicotopo.index import (
    Article,
    DicoTopoIndex,
    form_key,
    form_keys,
    parse_dicotopo,
    parse_with_stats,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dicotopo"
DT62 = FIXTURES / "DT62.xml"
DT59 = FIXTURES / "DT59.xml"


def test_parse_articles() -> None:
    articles = {a.id: a for a in parse_dicotopo(DT62)}
    assert set(articles) == {
        "P90000001",
        "P90000002",
        "P90000003",
        "P90000004",
        "P90000007",
    }
    commune = articles["P90000001"]
    assert commune.department == "62"
    assert commune.headword == "Hesdin-la-Forêt"
    assert commune.insee == "62447"
    assert commune.commune_insee == "62765"
    assert commune.kind is None
    hamlet = articles["P90000002"]
    assert hamlet.insee is None
    assert hamlet.commune_insee == "62447"
    assert hamlet.kind == "hameau"
    assert hamlet.forms == ("Fictimons", "Fictimontem")
    assert articles["P90000003"].kind == "lieu-dit"
    assert articles["P90000004"].kind == "chateau"


def test_malformed_articles_are_skipped() -> None:
    articles, skipped = parse_with_stats(DT62)
    assert len(articles) == 5
    assert skipped == 2


def test_lookup_by_form_and_department(tmp_path: Path) -> None:
    index = DicoTopoIndex(tmp_path / "dicotopo.sqlite")
    assert index.add_department("62", DT62, "2026-11-08") == (5, 2)
    index.add_department("59", DT59, "2026-11-08")
    assert index.departments() == {"62": "2026-11-08", "59": "2026-11-08"}
    found = index.lookup("fictimontem", "62")
    assert [a.id for a in found] == ["P90000002"]
    homonyms = index.lookup("le quesnoy fictif", "62")
    assert sorted(a.id for a in homonyms) == ["P90000003", "P90000004"]
    assert index.lookup("fictimontem", "59") == []
    assert [a.id for a in index.lookup("fictibosc", "59")] == ["P90000011"]
    article = index.get("P90000002")
    assert isinstance(article, Article)
    assert article.forms == ("Fictimons", "Fictimontem")
    assert index.get("P00000000") is None


def test_reindex_replaces_department(tmp_path: Path) -> None:
    index = DicoTopoIndex(tmp_path / "dicotopo.sqlite")
    index.add_department("62", DT62, "2026-11-08")
    index.add_department("62", DT62, "2026-11-09")
    assert index.departments() == {"62": "2026-11-09"}
    assert len(index.lookup("fictimons", "62")) == 1
    index.remove("62")
    assert index.departments() == {}
    assert index.lookup("fictimons", "62") == []
    assert index.get("P90000002") is None


def test_inverted_headword_is_indexed_fronted(tmp_path: Path) -> None:
    index = DicoTopoIndex(tmp_path / "dicotopo.sqlite")
    index.add_department("62", DT62, "2026-11-08")
    assert [a.id for a in index.lookup(form_key("Le Pré-Inventé"), "62")] == [
        "P90000007"
    ]
    assert [a.id for a in index.lookup(form_key("Pré-Inventé"), "62")] == []
    assert "l abbaye" in form_keys("Abbaye (L'),")
    assert "les fictives" in form_keys("Fictives(Les)")


def test_parse_error_keeps_old_department(tmp_path: Path) -> None:
    index = DicoTopoIndex(tmp_path / "dicotopo.sqlite")
    index.add_department("62", DT62, "2026-11-08")
    broken = tmp_path / "broken.xml"
    text = DT62.read_text(encoding="utf-8")
    broken.write_text(text[: len(text) // 2], encoding="utf-8")
    with pytest.raises(ParseError):
        index.add_department("62", broken, "2026-11-09")
    assert index.departments() == {"62": "2026-11-08"}
    assert len(index.lookup("fictimons", "62")) == 1


def test_duplicate_ids_keep_one_set_of_forms(tmp_path: Path) -> None:
    xml = tmp_path / "dup.xml"
    xml.write_text(
        "<DICTIONNAIRE dep='62'>"
        "<article id='P90000099'><vedette><sm>Dupli,</sm></vedette>"
        "<definition><typologie>ferme</typologie>, <localisation>"
        "<commune insee='62041'>Arras</commune></localisation></definition>"
        "<forme_ancienne><i>Duplus</i></forme_ancienne></article>"
        "<article id='P90000099'><vedette><sm>Dupli,</sm></vedette>"
        "<definition><typologie>ferme</typologie>, <localisation>"
        "<commune insee='62041'>Arras</commune></localisation></definition>"
        "<forme_ancienne><i>Duplus</i></forme_ancienne></article>"
        "</DICTIONNAIRE>",
        encoding="utf-8",
    )
    index = DicoTopoIndex(tmp_path / "dicotopo.sqlite")
    index.add_department("62", xml, "2026-11-08")
    assert len(index.lookup("duplus", "62")) == 1


def test_stored_department_is_the_argument(tmp_path: Path) -> None:
    index = DicoTopoIndex(tmp_path / "dicotopo.sqlite")
    index.add_department("99", DT62, "2026-11-08")
    found = index.lookup("fictimons", "99")
    assert [a.department for a in found] == ["99"]
    article = index.get("P90000002")
    assert article is not None
    assert article.department == "99"
