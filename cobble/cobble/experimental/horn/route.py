"""The tests a way passes on its route that are not its decisions: in each context it runs through, every test on a path from the context's entry to where the way goes next, and every test in a range performed on that path."""

from __future__ import annotations

import networkx as nx
from cobble.dataflow.srccfg.cfg import Edge, NodeKind
from cobble.experimental.horn.context import Context, perform_edge, performed, top
from cobble.experimental.horn.followed import unfollowed
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.ways import Flow, Way, flow_of


def route_tests(program: Program, way: Way, node: str) -> tuple[str, ...]:
    cut = unfollowed(program)
    cfg = program.cfg
    legs = tuple(
        zip(
            (top(cfg), *(context for context, _ in way.calls)),
            (*(call for _, call in way.calls), node),
            strict=True,
        )
    )
    passed = frozenset(
        visited
        for context, target in legs
        for visited in _performed(
            program, cut, _between(flow_of(program, context, cut), target), frozenset()
        )
    )
    decided = frozenset(decision.test for decision in way.decisions)
    return tuple(
        sorted(
            n for n in passed - decided - {node} if cfg.node(n).kind is NodeKind.TEST
        )
    )


def _between(flow: Flow, target: str) -> frozenset[str]:
    """The nodes on some path from the context's entry to ``target``, short of it."""
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(flow.nodes)
    graph.add_edges_from((source, end) for source, end, _ in flow.arcs)
    if target not in flow.nodes:
        return frozenset()
    after = nx.descendants(graph, flow.context.entry) | {flow.context.entry}
    return frozenset(after & nx.ancestors(graph, target))


def _performed(
    program: Program,
    cut: frozenset[Edge],
    nodes: frozenset[str],
    seen: frozenset[Context],
) -> frozenset[str]:
    """``nodes``, and every node of each range a PERFORM among them enters, at
    any depth."""
    cfg = program.cfg
    ranges = (
        frozenset(performed(cfg, edge) for n in nodes for edge in perform_edge(cfg, n))
        - seen
    )
    inner = frozenset(
        visited
        for range_ in ranges
        for visited in _performed(
            program, cut, flow_of(program, range_, cut).nodes, seen | ranges
        )
    )
    return nodes | inner
