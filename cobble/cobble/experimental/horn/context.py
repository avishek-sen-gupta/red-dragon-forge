"""Where a node runs: the top level, or inside one PERFORM range, and the nodes each can reach."""

from dataclasses import dataclass

import networkx as nx
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind

NOT_FOLLOWED = (EdgeKind.RETURN, EdgeKind.PERFORM)


@dataclass(frozen=True)
class Context:
    entry: str
    end: str

    @property
    def is_range(self) -> bool:
        return self.end != ""


def top(cfg: Cfg) -> Context:
    return Context(cfg.entry, "")


def perform_edge(cfg: Cfg, node: str) -> tuple[Edge, ...]:
    return tuple(e for e in cfg.successors(node) if e.kind is EdgeKind.PERFORM)


def performed(cfg: Cfg, edge: Edge) -> Context:
    return Context(edge.target, cfg.node(edge.source).range_end)


def contexts(cfg: Cfg) -> tuple[Context, ...]:
    ranges = frozenset(
        performed(cfg, edge) for edge in cfg.edges if edge.kind is EdgeKind.PERFORM
    )
    return (top(cfg), *sorted(ranges, key=lambda c: (c.entry, c.end)))


def steps(cfg: Cfg, context: Context, node: str) -> tuple[Edge, ...]:
    return tuple(
        edge
        for edge in cfg.successors(node)
        if edge.kind not in NOT_FOLLOWED
        and not (edge.kind is EdgeKind.FALLTHRU and edge.source == context.end)
    )


def _resumes(cfg: Cfg, node: str) -> tuple[tuple[str, str], ...]:
    resume = cfg.node(node).resume
    return ((node, resume),) if perform_edge(cfg, node) and resume else ()


def members(cfg: Cfg, context: Context) -> frozenset[str]:
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(cfg.node_ids)
    graph.add_edges_from(
        (edge.source, edge.target)
        for node in cfg.node_ids
        for edge in steps(cfg, context, node)
    )
    graph.add_edges_from(pair for node in cfg.node_ids for pair in _resumes(cfg, node))
    return frozenset({context.entry, *nx.descendants(graph, context.entry)})
