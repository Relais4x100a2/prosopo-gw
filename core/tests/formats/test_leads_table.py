"""Table ``pistes`` tirée des notes (fixtures 100 % synthétiques)."""

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet

from geneweb_py.core.family import Family
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.person import Person
from geneweb_py.formats.leads_table import PISTES, build_leads_table
from geneweb_py.formats.tables import Row

GW = """encoding: utf-8
gwplus

fam DUPONT Jean + MARTIN Marie
comm "Associés dans une société de transport"
fevt
#marr 1900 #p Lyon
note Repas servi à l'usine du village
end fevt
beg
end

notes DUPONT Jean
beg
Employé de la banque du village.
end notes

pevt DUPONT Jean
#resi 1895 #p Lyon
note Logé près de la fabrique
end pevt

pevt MARTIN Marie
#occu 1902 #p Lyon
note Employée à la Banque Fictive
end pevt
"""

COLUMNS = [
    "piste_id",
    "personne_id",
    "evenement_id",
    "famille_id",
    "nature",
    "origine",
    "mots",
    "type_devine",
    "forte",
    "extrait",
]


def _genealogy() -> Genealogy:
    return GeneWebParser(validate=False).parse_string(GW)


def _rows(
    genealogy: Genealogy,
    linked: Mapping[str, AbstractSet[str]] | None = None,
    ignored_words: Iterable[str] = (),
) -> list[Row]:
    return build_leads_table(genealogy, linked or {}, ignored_words).rows


def _marie(genealogy: Genealogy) -> str:
    return next(pid for pid, p in genealogy.persons.items() if p.first_name == "Marie")


def test_columns() -> None:
    assert PISTES.name == "pistes"
    assert PISTES.column_names == COLUMNS
    assert PISTES.primary_key == "piste_id"
    assert all(c.description for c in PISTES.columns)
    assert {c.name: c.type for c in PISTES.columns}["forte"] == "bool"


def test_each_origin() -> None:
    rows = _rows(_genealogy())
    assert {r["origine"] for r in rows} == {
        "personne",
        "evenement",
        "famille",
        "evenement_familial",
    }
    for r in rows:
        assert r["nature"] == "organisation"
        assert list(r) == COLUMNS
        event_id = r["evenement_id"]
        if r["origine"] == "evenement":
            assert str(event_id).startswith("pevt:")
        elif r["origine"] == "evenement_familial":
            assert str(event_id).startswith("fevt:")
        else:
            assert event_id is None
        family = r["origine"] in ("famille", "evenement_familial")
        assert (r["famille_id"] is not None) is family
        assert r["personne_id"] is not None


def test_family_note_owner() -> None:
    g = Genealogy()
    g.persons["W"] = Person(last_name="MARTIN", first_name="Anne")
    g.families["F1"] = Family(
        family_id="F1", wife_id="W", comments=["Tenait une boutique"]
    )
    g.families["F2"] = Family(family_id="F2", comments=["Tenait une boutique"])
    owners = {r["famille_id"]: r["personne_id"] for r in _rows(g)}
    assert owners == {"F1": "W", "F2": None}


def test_occupation_note_used_by_org_skipped() -> None:
    g = _genealogy()
    marie = _marie(g)
    kept = [r for r in _rows(g) if r["personne_id"] == marie]
    assert [r["evenement_id"] for r in kept] == [f"pevt:{marie}:0"]
    assert kept[0]["forte"] is True
    linked = {f"pevt:{marie}:0": {"Banque Fictive"}}
    skipped = [r for r in _rows(g, linked) if r["personne_id"] == marie]
    assert skipped == []


def test_occupation_note_kept_when_org_named_elsewhere() -> None:
    g = _genealogy()
    marie = _marie(g)
    # Événement rattaché à une autre organisation (nommée par le complément) :
    # la note n'a pas servi, la banque reste une piste.
    linked = {f"pevt:{marie}:0": {"Usine Fictive"}}
    kept = [r for r in _rows(g, linked) if r["personne_id"] == marie]
    assert [r["mots"] for r in kept] == ["banque"]


def test_ignored_words_passed() -> None:
    rows = _rows(_genealogy(), ignored_words=["banque"])
    assert all("banque" not in str(r["mots"]).split() for r in rows)
    assert rows


def test_ids_stable_and_unique() -> None:
    first = [r["piste_id"] for r in _rows(_genealogy())]
    second = [r["piste_id"] for r in _rows(_genealogy())]
    assert first == second
    assert len(set(first)) == len(first)
    assert all(str(i).startswith("p-") and len(str(i)) == 14 for i in first)


def test_empty_genealogy() -> None:
    table = build_leads_table(Genealogy(), {}, [])
    assert table.spec is PISTES
    assert table.rows == []
