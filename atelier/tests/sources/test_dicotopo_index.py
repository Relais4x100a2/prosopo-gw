from pathlib import Path

from prosopo_gw_atelier.sources.dicotopo.index import (
    Article,
    DicoTopoIndex,
    parse_dicotopo,
    parse_with_stats,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dicotopo"
DT62 = FIXTURES / "DT62.xml"
DT59 = FIXTURES / "DT59.xml"


def test_parse_articles() -> None:
    articles = {a.id: a for a in parse_dicotopo(DT62)}
    assert set(articles) == {"P90000001", "P90000002", "P90000003", "P90000004"}
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
    assert len(articles) == 4
    assert skipped == 2


def test_lookup_by_form_and_department(tmp_path: Path) -> None:
    index = DicoTopoIndex(tmp_path / "dicotopo.sqlite")
    assert index.add_department("62", DT62, "2026-11-08") == (4, 2)
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
