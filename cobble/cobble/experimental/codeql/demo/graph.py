"""CodeQL's graph as the WebGL renderer takes it, and the same graph with each query's path steps added."""

from collections.abc import Mapping

import networkx as nx
from cobble.experimental.codeql.demo.demo_results import DemoResults
from cobble.knowledge_graph.drawn_node import DrawnNode


def _drawn_nodes(results: DemoResults) -> Mapping[tuple[str, str], DrawnNode]:
    return {
        (n.program, n.node): (n.kind, f"{n.program}:{n.node}") for n in results.nodes
    }


def control_graph(results: DemoResults) -> nx.MultiDiGraph:
    node_of = _drawn_nodes(results)
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(
        (node_of[(n.program, n.node)], {"kind": n.kind, "id": n.label})
        for n in results.nodes
    )
    graph.add_edges_from(
        (
            node_of[(e.program, e.source)],
            node_of[(e.program, e.target)],
            {"kind": e.kind},
        )
        for e in results.edges
    )
    return graph


def with_flows(control: nx.MultiDiGraph, results: DemoResults) -> nx.MultiDiGraph:
    node_of = _drawn_nodes(results)
    drawn = control.copy()
    drawn.add_edges_from(
        (node_of[(s.program, s.source)], node_of[(s.program, s.target)], {"kind": kind})
        for kind, steps in results.flows.items()
        for s in steps
    )
    return drawn
