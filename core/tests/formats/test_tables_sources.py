"""Table ``sources`` de l'export. Fixtures 100 % synthétiques."""

from pathlib import Path

from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.formats.tables import Table, build_base_tables

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rich_pevt_wit.gw"

GW = """encoding: utf-8
gwplus

fam DUPONT Jean 1870 #bs RegistreN #ds RegistreD #src Etatcivil +1900 #ms RegistreM MARTIN Marie #csrc Livret
src Acte
beg
- h Louis 1901
end

pevt DUPONT Jean
#birt 1870 #s RegistreN
#occu #s Annuaire
end pevt
"""


def _genealogy() -> Genealogy:
    return GeneWebParser().parse_string(GW)


def _sources(genealogy: Genealogy) -> Table:
    return {t.spec.name: t for t in build_base_tables(genealogy)}["sources"]


def _triples(table: Table) -> list[tuple[object, object, object, object]]:
    return [(r["cible"], r["cible_id"], r["objet"], r["texte"]) for r in table.rows]


def test_each_source_field_becomes_a_row() -> None:
    g = _genealogy()
    jean = g.persons["DUPONT_Jean_0"]
    assert jean.birth_source == "RegistreN"
    assert jean.death_source == "RegistreD"
    assert jean.person_source == "Etatcivil"
    family = g.families["FAM_001"]
    assert family.marriage_source == "RegistreM"
    assert family.family_source == "Acte"
    assert family.common_children_source == "Livret"
    triples = _triples(_sources(g))
    for expected in [
        ("personne", "DUPONT_Jean_0", "generale", "Etatcivil"),
        ("personne", "DUPONT_Jean_0", "naissance", "RegistreN"),
        ("personne", "DUPONT_Jean_0", "deces", "RegistreD"),
        ("famille", "FAM_001", "generale", "Acte"),
        ("famille", "FAM_001", "mariage", "RegistreM"),
        ("famille", "FAM_001", "enfants", "Livret"),
        ("evenement", "pevt:DUPONT_Jean_0:1", "evenement", "Annuaire"),
    ]:
        assert expected in triples


def test_event_source_row() -> None:
    triples = _triples(_sources(GeneWebParser().parse_file(str(FIXTURE))))
    events = [t for t in triples if t[0] == "evenement"]
    assert [t[3] for t in events] == ["Archives"]
    assert events[0][2] == "evenement"


def test_birth_source_not_duplicated() -> None:
    rows = [r for r in _sources(_genealogy()).rows if r["texte"] == "RegistreN"]
    assert [(r["cible"], r["objet"]) for r in rows] == [("personne", "naissance")]


def test_source_ids_unique_and_stable() -> None:
    first = [r["source_id"] for r in _sources(_genealogy()).rows]
    second = [r["source_id"] for r in _sources(_genealogy()).rows]
    assert first == second
    assert len(set(first)) == len(first)
    for sid in first:
        assert isinstance(sid, str) and sid.startswith("s-") and len(sid) == 14


def test_blank_source_ignored() -> None:
    g = _genealogy()
    g.persons["DUPONT_Jean_0"].death_source = "   "
    g.families["FAM_001"].family_source = ""
    objets = {(r["cible"], r["objet"]) for r in _sources(g).rows}
    assert ("personne", "deces") not in objets
    assert ("famille", "generale") not in objets


def test_sources_table_is_last() -> None:
    names = [t.spec.name for t in build_base_tables(_genealogy())]
    assert names[-1] == "sources" and len(names) == 6


def test_underscores_decoded_in_every_source() -> None:
    text = (
        "encoding: utf-8\ngwplus\n\n"
        "fam DUPONT Jean #bs Registre_paroissial #src Notaire_Fictif"
        " +1900 #ms Acte_de_mariage MARTIN Marie\n\n"
        "pevt DUPONT Jean\n#Cours_peinture 1890 #s Liste_eleves\nend pevt\n"
    )
    texts = {r["texte"] for r in _sources(GeneWebParser().parse_string(text)).rows}
    assert {
        "Registre paroissial",
        "Notaire Fictif",
        "Acte de mariage",
        "Liste eleves",
    } <= texts
    assert not any("_" in str(t) for t in texts)
