"""Tables d'organisations de l'export (fixtures 100 % synthétiques)."""

from typing import Dict, Set

import pytest

from geneweb_py.api.services import organization_candidates as oc
from geneweb_py.api.services.organization_candidates import build_candidate_index
from geneweb_py.api.services.organization_exports import (
    candidates_csv,
    links_csv,
    shared_experiences_csv,
)
from geneweb_py.api.services.organization_tables import build_organization_tables
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.shared_experiences import find_shared_experiences
from geneweb_py.formats.tables import Table, build_base_tables

GW = """encoding: utf-8

fam DUPONT Jean + MARTIN Marie
beg
end

pevt DUPONT Jean
#occu 1900 #p [Banque Fictive] - Lyon
#Deportation 1943 #p Villefictive
#Philatelie_Locale 1905 #p Villefictive
end pevt

pevt MARTIN Marie
#occu 1902 #p [Banque Fictive] - Lyon
#Deportation 1943 #p Villefictive
end pevt

pevt DURAND Paul
#Voyage_Italie 1950 #p Montfictif
end pevt

notes DURAND Paul
beg
Apprenti dans un atelier du quartier.
end notes
"""


def _genealogy() -> Genealogy:
    return GeneWebParser(validate=False).parse_string(GW)


def _build(genealogy: Genealogy) -> Dict[str, Table]:
    index = build_candidate_index(genealogy)
    shared = find_shared_experiences(genealogy, index.matched)
    return {t.spec.name: t for t in build_organization_tables(genealogy, index, shared)}


def _event_ids(genealogy: Genealogy) -> Set[object]:
    (events,) = [t for t in build_base_tables(genealogy) if t.spec.name == "evenements"]
    return {r["evenement_id"] for r in events.rows}


def test_table_order_and_columns() -> None:
    g = _genealogy()
    index = build_candidate_index(g)
    built = build_organization_tables(
        g, index, find_shared_experiences(g, index.matched)
    )
    assert [t.spec.name for t in built] == [
        "organisations",
        "liens",
        "reste_a_classer",
        "pistes",
        "experiences_proches",
    ]
    for table in built:
        assert table.rows
        for row in table.rows:
            assert list(row) == table.spec.column_names


def test_organisation_row() -> None:
    (row,) = _build(_genealogy())["organisations"].rows
    assert row["nom"] == "Banque Fictive"
    assert row["type"] == "company"
    assert row["type_libelle"] == "Entreprise"
    assert row["nb_personnes"] == 2
    assert row["premiere_annee"] == 1900 and row["derniere_annee"] == 1902
    assert isinstance(row["a_revoir"], bool) and isinstance(row["collectif"], bool)


def test_link_row_has_event_id() -> None:
    g = _genealogy()
    rows = _build(g)["liens"].rows
    assert [r["personne_id"] for r in rows] == ["DUPONT_Jean_0", "MARTIN_Marie_0"]
    events = _event_ids(g)
    for r in rows:
        assert isinstance(r["evenement_id"], str) and r["evenement_id"].startswith(
            "pevt:"
        )
        assert r["evenement_id"] in events
        assert r["temoin"] is False
        assert r["statut"] == "" and r["nom_retenu"] == ""
    assert rows[0]["annee"] == 1900


def test_unmatched_rows() -> None:
    g = _genealogy()
    rows = _build(g)["reste_a_classer"].rows
    assert [r["evenement_id"] for r in rows] == [
        "pevt:DUPONT_Jean_0:2",
        "pevt:DURAND_Paul_0:0",
    ]
    assert all(r["evenement_id"] in _event_ids(g) for r in rows)
    assert {r["mot"] for r in rows} == {oc.OTHERS_WORD}


def test_unmatched_excludes_shared_experiences() -> None:
    rows = _build(_genealogy())["reste_a_classer"].rows
    ids = {r["evenement_id"] for r in rows}
    assert "pevt:DUPONT_Jean_0:1" not in ids  # Déportation : expérience proche


def test_unmatched_not_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ["encoding: utf-8", ""]
    for i in range(3):
        name = chr(65 + i)
        lines += [
            f"pevt DUPONT Jean{name}",
            f"#Voyage_{name} 19{10 + 20 * i}",
            "end pevt",
            "",
        ]
    g = GeneWebParser(validate=False).parse_string("\n".join(lines))
    monkeypatch.setattr(oc, "UNMATCHED_GROUP_CAP", 1)
    assert len(_build(g)["reste_a_classer"].rows) == 3


def test_shared_experience_rows_have_ids() -> None:
    g = _genealogy()
    rows = _build(g)["experiences_proches"].rows
    persons = set(g.persons)
    events = _event_ids(g)
    assert rows
    for r in rows:
        assert r["personne_id"] in persons
        assert r["evenement_id"] in events
    deportation = [r for r in rows if r["evenement"] == "Deportation"]
    assert {r["evenement_id"] for r in deportation} == {
        "pevt:DUPONT_Jean_0:1",
        "pevt:MARTIN_Marie_0:1",
    }
    assert deportation[0]["annee"] == "1943"


def test_building_tables_leaves_csv_exports_untouched() -> None:
    g = _genealogy()
    index = build_candidate_index(g)
    shared = find_shared_experiences(g, index.matched)
    before = (
        candidates_csv(index),
        links_csv(index),
        shared_experiences_csv(g, shared),
    )
    build_organization_tables(g, index, shared)
    after = (candidates_csv(index), links_csv(index), shared_experiences_csv(g, shared))
    assert before == after
    assert links_csv(index).splitlines()[0] == (
        "﻿organisation_id;organisation;personne_id;personne;role;date;lieu;"
        "type_evenement;evenement;nb_temoins;statut;nom_retenu"
    )
