"""Réseau prosopographique : nœuds, arêtes pondérées, exports. Données synthétiques."""

import json

import pytest

from geneweb_py.analytics.network import (
    EDGE_MEMBER,
    NODE_EVENT,
    NODE_ORG,
    NODE_PERSON,
    build_network,
)
from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """encoding: utf-8
gwplus

fam DUPONT Jean + MARTIN Marie
beg
- h DUPONT Louis
end

pevt DUPONT Jean
#Membre_Academie 1900
wit m: MARTIN Marie
#Membre_Academie 1910
#Cours_peinture 1890 #p [Atelier_Rose]_-_Lyon
end pevt

pevt MARTIN Marie
#Membre_Academie 1905
end pevt
"""


@pytest.fixture
def genealogy():
    g = GeneWebParser().parse_string(GW)
    g.infer_organizations()
    return g


def _ids(network, kind):
    return {n.id for n in network.nodes if n.kind == kind}


class TestBuildNetwork:
    def test_node_kinds(self, genealogy):
        network = build_network(genealogy)
        assert len(_ids(network, NODE_PERSON)) == len(genealogy.persons)
        assert _ids(network, NODE_ORG) == {"org:academie", "org:atelier_rose_lyon"}
        assert _ids(network, NODE_EVENT) == set()

    def test_membership_edges_are_weighted_by_link_count(self, genealogy):
        network = build_network(genealogy)
        jean = next(k for k, p in genealogy.persons.items() if p.first_name == "Jean")
        edge = network.edge(f"person:{jean}", "org:academie")
        assert edge.kind == EDGE_MEMBER
        assert edge.weight == 2

    def test_node_labels_and_attributes(self, genealogy):
        network = build_network(genealogy)
        org = network.node("org:atelier_rose_lyon")
        assert org.label == "Atelier Rose"
        assert org.attrs["place"] == "Lyon"
        assert org.attrs["type"] == "company"  # mot d'établissement « atelier »

    def test_events_option_adds_event_nodes_with_participants(self, genealogy):
        network = build_network(genealogy, include_events=True)
        events = _ids(network, NODE_EVENT)
        assert len(events) == 4  # 3 événements de Jean + 1 de Marie
        kinds = {e.kind for e in network.edges}
        assert {"participant", "organization", "witness"} <= kinds

    def test_families_option_adds_kinship_edges(self, genealogy):
        plain = build_network(genealogy)
        kin = build_network(genealogy, include_families=True)
        assert len(kin.edges) - len(plain.edges) == 3  # conjoints + 2 filiations

    def test_edges_never_dangle(self, genealogy):
        network = build_network(genealogy, include_events=True, include_families=True)
        ids = {n.id for n in network.nodes}
        assert all(e.source in ids and e.target in ids for e in network.edges)

    def test_empty_genealogy(self):
        from geneweb_py.core.genealogy import Genealogy

        network = build_network(Genealogy())
        assert network.nodes == [] and network.edges == []


class TestCoMembership:
    def test_people_sharing_an_organization_are_linked(self, genealogy):
        network = build_network(genealogy).co_membership()
        assert {n.kind for n in network.nodes} == {NODE_PERSON}
        assert len(network.edges) == 1
        assert network.edges[0].weight == 1  # une seule organisation partagée


class TestExports:
    def test_json_for_visjs(self, genealogy, tmp_path):
        target = tmp_path / "net.json"
        build_network(genealogy).export_json(target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert {"nodes", "edges"} <= set(data)
        assert data["nodes"][0].keys() >= {"id", "label", "group"}
        assert data["edges"][0].keys() >= {"from", "to", "value"}

    def test_networkx_graph(self, genealogy):
        nx = pytest.importorskip("networkx")
        graph = build_network(genealogy).to_networkx()
        assert isinstance(graph, nx.Graph)
        assert graph.number_of_nodes() == len(build_network(genealogy).nodes)
        assert graph.nodes["org:academie"]["kind"] == NODE_ORG
        jean = next(
            n for n, d in graph.nodes(data=True) if d.get("label", "").endswith("Jean")
        )
        assert graph.edges[jean, "org:academie"]["weight"] == 2

    def test_graphml_and_gexf(self, genealogy, tmp_path):
        pytest.importorskip("networkx")
        network = build_network(genealogy)
        network.export_graphml(tmp_path / "net.graphml")
        network.export_gexf(tmp_path / "net.gexf")
        assert "graphml" in (tmp_path / "net.graphml").read_text(encoding="utf-8")
        assert "gexf" in (tmp_path / "net.gexf").read_text(encoding="utf-8")

    def test_pyvis_html(self, genealogy, tmp_path):
        pytest.importorskip("pyvis")
        target = tmp_path / "net.html"
        build_network(genealogy).export_pyvis_html(target)
        assert "vis-network" in target.read_text(encoding="utf-8")

    def test_missing_optional_dependency_gives_clear_error(
        self, genealogy, monkeypatch
    ):
        import importlib

        real = importlib.import_module

        def fake(name, *args, **kwargs):
            if name == "networkx":
                raise ImportError("no networkx")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake)
        with pytest.raises(ImportError, match="analytics"):
            build_network(genealogy).to_networkx()
