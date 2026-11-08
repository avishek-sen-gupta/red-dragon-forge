"""Keep only the tests at nodes from which some path leads to the goal: past every other test the goal is out of reach either way, so leaving it out changes no answer."""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
from cobble.dataflow.srccfg.cfg import Atom, Cfg, NodeKind
from cobble.experimental.horn.kept_tests import KeptTests


@dataclass(frozen=True)
class LeadingTo(KeptTests):
    atoms: frozenset[Atom]

    def keeps(self, atom: Atom) -> bool:
        return atom in self.atoms


def leading_to(cfg: Cfg, goal: str) -> LeadingTo:
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(cfg.node_ids)
    graph.add_edges_from((edge.source, edge.target) for edge in cfg.edges)
    before = nx.ancestors(graph, goal) | {goal}
    return LeadingTo(
        frozenset(
            node.atom
            for node in cfg.nodes
            if node.kind is NodeKind.TEST and node.id in before
        )
    )
