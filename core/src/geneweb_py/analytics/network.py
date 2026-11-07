"""Réseau prosopographique : personnes, organisations et événements.

Remplace le script historique de ``Geneweb`` (V2, ``data_export/network.py``) qui
reconstruisait le graphe depuis des CSV. Ici le graphe est construit directement depuis
``Genealogy`` et ses ``Organization`` / ``OrganizationLink``.

La construction (``build_network``) et l'export JSON (vis.js) n'ont aucune dépendance.
``to_networkx``, GraphML, GEXF et Pyvis exigent l'extra ``analytics``.
"""

import importlib
import json
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.genealogy import Genealogy

NODE_PERSON = "person"
NODE_ORG = "organization"
NODE_EVENT = "event"

EDGE_MEMBER = "member"
EDGE_PARTICIPANT = "participant"
EDGE_ORGANIZATION = "organization"
EDGE_WITNESS = "witness"
EDGE_SPOUSE = "spouse"
EDGE_PARENT = "parent"
EDGE_CO_MEMBER = "co_member"

PathLike = str | Path


def _require(module: str) -> Any:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(
            f"'{module}' est requis pour cet export : "
            "installer l'extra avec `uv sync --extra analytics`."
        ) from exc


@dataclass
class NetworkNode:
    id: str
    label: str
    kind: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class NetworkEdge:
    source: str
    target: str
    kind: str
    weight: int = 1


@dataclass
class Network:
    """Graphe non orienté, indépendant de toute bibliothèque."""

    nodes: list[NetworkNode] = field(default_factory=list)
    edges: list[NetworkEdge] = field(default_factory=list)

    def node(self, node_id: str) -> NetworkNode:
        return next(n for n in self.nodes if n.id == node_id)

    def edge(self, a: str, b: str) -> NetworkEdge:
        """Arête entre ``a`` et ``b`` (dans un sens ou dans l'autre)."""
        return next(e for e in self.edges if {e.source, e.target} == {a, b})

    def co_membership(self) -> "Network":
        """Projection sur les personnes : lien pondéré par le nombre d'organisations
        partagées."""
        members: dict[str, set[str]] = {}
        for e in self.edges:
            if e.kind == EDGE_MEMBER:
                members.setdefault(e.target, set()).add(e.source)
        shared: dict[tuple[str, str], int] = {}
        for people in members.values():
            for pair in combinations(sorted(people), 2):
                shared[pair] = shared.get(pair, 0) + 1
        used = {p for pair in shared for p in pair}
        return Network(
            nodes=[n for n in self.nodes if n.id in used],
            edges=[
                NetworkEdge(a, b, EDGE_CO_MEMBER, weight)
                for (a, b), weight in shared.items()
            ],
        )

    # -- Exports ----------------------------------------------------------
    def export_json(self, path: PathLike) -> Path:
        """JSON ``{"nodes": [...], "edges": [...]}`` directement lisible par vis.js."""
        payload = {
            "nodes": [
                {"id": n.id, "label": n.label, "group": n.kind, **n.attrs}
                for n in self.nodes
            ],
            "edges": [
                {"from": e.source, "to": e.target, "value": e.weight, "title": e.kind}
                for e in self.edges
            ],
        }
        target = Path(path)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return target

    def to_networkx(self) -> Any:
        """``networkx.Graph`` (attributs ``kind``, ``label``, ``weight``)."""
        nx = _require("networkx")
        graph = nx.Graph()
        for n in self.nodes:
            graph.add_node(n.id, label=n.label, kind=n.kind, **n.attrs)
        for e in self.edges:
            graph.add_edge(e.source, e.target, kind=e.kind, weight=e.weight)
        return graph

    def export_graphml(self, path: PathLike) -> Path:
        nx = _require("networkx")
        nx.write_graphml(self.to_networkx(), str(path), encoding="utf-8")
        return Path(path)

    def export_gexf(self, path: PathLike) -> Path:
        nx = _require("networkx")
        nx.write_gexf(self.to_networkx(), str(path), encoding="utf-8")
        return Path(path)

    def export_pyvis_html(self, path: PathLike, height: str = "750px") -> Path:
        """Page HTML autonome (bibliothèque embarquée, aucun accès réseau)."""
        pyvis_network = _require("pyvis.network")
        vis = pyvis_network.Network(
            height=height, width="100%", cdn_resources="in_line", notebook=False
        )
        for n in self.nodes:
            vis.add_node(n.id, label=n.label, group=n.kind)
        for e in self.edges:
            vis.add_edge(e.source, e.target, value=e.weight, title=e.kind)
        target = Path(path)
        vis.write_html(str(target), notebook=False)
        return target


def _person_label(person: Any) -> str:
    return f"{person.last_name} {person.first_name}".strip()


def build_network(
    genealogy: "Genealogy",
    include_events: bool = False,
    include_families: bool = False,
) -> Network:
    """Construit le réseau prosopographique d'une généalogie.

    Nœuds ``person:<id>`` et ``org:<id>`` ; arête ``member`` personne -> organisation
    pondérée par le nombre de ``OrganizationLink``.

    Args:
        include_events: ajoute un nœud par événement à l'origine d'un lien,
            relié à son titulaire (``participant``), à l'organisation (``organization``)
            et à ses témoins (``witness``).
        include_families: ajoute les liens de parenté (``spouse``, ``parent``).
    """
    network = Network()
    node_ids: set[str] = set()
    weights: dict[tuple[str, str, str], int] = {}

    def add_node(node: NetworkNode) -> None:
        if node.id not in node_ids:
            node_ids.add(node.id)
            network.nodes.append(node)

    def add_edge(source: str, target: str, kind: str) -> None:
        weights[(source, target, kind)] = weights.get((source, target, kind), 0) + 1

    for person_id, person in genealogy.persons.items():
        add_node(NetworkNode(f"person:{person_id}", _person_label(person), NODE_PERSON))

    for org in genealogy.organizations.values():
        attrs = {
            "type": org.type.value,
            "place": org.place,
            "confidence": org.confidence,
            "needs_review": org.needs_review,
        }
        add_node(
            NetworkNode(
                f"org:{org.id}",
                org.name,
                NODE_ORG,
                {k: v for k, v in attrs.items() if v is not None},
            )
        )

    for link in genealogy.organization_links:
        add_edge(f"person:{link.person_id}", f"org:{link.organization_id}", EDGE_MEMBER)

    if include_events:
        _add_events(genealogy, add_node, add_edge)

    if include_families:
        for family in genealogy.families.values():
            if family.husband_id and family.wife_id:
                add_edge(
                    f"person:{family.husband_id}",
                    f"person:{family.wife_id}",
                    EDGE_SPOUSE,
                )
            for child in family.children:
                for parent_id in (family.husband_id, family.wife_id):
                    if parent_id:
                        add_edge(
                            f"person:{parent_id}",
                            f"person:{child.person_id}",
                            EDGE_PARENT,
                        )

    network.edges = [
        NetworkEdge(source, target, kind, weight)
        for (source, target, kind), weight in weights.items()
        if source in node_ids and target in node_ids
    ]
    return network


def _add_events(genealogy: "Genealogy", add_node: Any, add_edge: Any) -> None:
    for person_id, person in genealogy.persons.items():
        links = genealogy.get_organization_links(person_id=person_id)
        for index, event in enumerate(person.events):
            date = event.date.display_text if event.date else None
            matching = [
                link
                for link in links
                if link.source_event_type == event.event_type_raw
                and (link.start_date.display_text if link.start_date else None) == date
            ]
            if not matching:
                continue
            event_id = f"event:{person_id}:{index}"
            label = " ".join(p for p in (event.event_type_raw, date) if p)
            add_node(
                NetworkNode(
                    event_id,
                    label,
                    NODE_EVENT,
                    {"place": event.place} if event.place else {},
                )
            )
            add_edge(f"person:{person_id}", event_id, EDGE_PARTICIPANT)
            for link in matching:
                add_edge(event_id, f"org:{link.organization_id}", EDGE_ORGANIZATION)
            for witness in event.witnesses:
                witness_id = witness.get("person_id")
                if witness_id:
                    add_edge(f"person:{witness_id}", event_id, EDGE_WITNESS)
