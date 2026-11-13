"""The ways a node is reached: chains of the tests it is control dependent on, per context, prefixed by a way to each call site of its range."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from itertools import groupby, islice, product

import networkx as nx
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, NodeKind
from cobble.experimental.horn.context import (
    Context,
    contexts,
    perform_edge,
    performed,
    steps,
)
from cobble.experimental.horn.entries import entries_of
from cobble.experimental.horn.followed import unfollowed
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.program import Program

logger = logging.getLogger(__name__)

MAX_WAYS = 64
START = "%start"
EXIT = "%exit"
DECIDING: Mapping[EdgeKind, Outcome] = {
    EdgeKind.TRUE: Outcome.TRUE,
    EdgeKind.FALSE: Outcome.FALSE,
}

Arc = tuple[str, str, EdgeKind]
Parent = tuple[str, EdgeKind]


@dataclass(frozen=True)
class Decision:
    test: str
    outcome: Outcome


@dataclass(frozen=True)
class Way:
    """``calls`` are the ranges the way enters and the PERFORM it enters each
    through, outermost first."""

    decisions: tuple[Decision, ...]
    calls: tuple[tuple[Context, str], ...]


@dataclass(frozen=True)
class Ways:
    """``cut`` when there were more than ``MAX_WAYS`` and the rest are left out."""

    ways: tuple[Way, ...]
    cut: bool


@dataclass(frozen=True)
class Flow:
    """One context's followed arcs from its entry: the nodes they reach, what each
    node is control dependent on, and its immediate dominator."""

    context: Context
    arcs: tuple[Arc, ...]
    nodes: frozenset[str]
    parents: Mapping[str, tuple[Parent, ...]]
    dominators: Mapping[str, str]

    def exits(self) -> frozenset[str]:
        """The nodes with no followed arc out: the context's end, and every node
        that ends the task or leaves the context for good."""
        sources = frozenset(arc[0] for arc in self.arcs)
        return self.nodes - sources

    def dominated(self, node: str) -> tuple[str, ...]:
        """The nodes that dominate ``node``, from the entry down, without it."""
        up = self.dominators.get(node, node)
        return () if up == node else (*self.dominated(up), up)


def flow_of(program: Program, context: Context, cut: frozenset[Edge]) -> Flow:
    cfg = program.cfg
    arcs = _reached(cfg, context, _arcs(cfg, context, cut))
    nodes = frozenset({context.entry, *(arc[1] for arc in arcs)})
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from((arc[0], arc[1]) for arc in arcs)
    return Flow(
        context,
        arcs,
        nodes,
        _dependence(graph, arcs, context),
        nx.immediate_dominators(graph, context.entry),
    )


def _arcs(cfg: Cfg, context: Context, cut: frozenset[Edge]) -> tuple[Arc, ...]:
    followed = tuple(
        (edge.source, edge.target, edge.kind)
        for node in sorted(cfg.node_ids)
        for edge in steps(cfg, context, node)
        if edge not in cut
    )
    resumed = tuple(
        (node, cfg.node(node).resume, EdgeKind.FLOW)
        for node in sorted(cfg.node_ids)
        if perform_edge(cfg, node) and cfg.node(node).resume
    )
    return (*followed, *resumed)


def _reached(cfg: Cfg, context: Context, arcs: tuple[Arc, ...]) -> tuple[Arc, ...]:
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(cfg.node_ids)
    graph.add_edges_from((arc[0], arc[1]) for arc in arcs)
    reach = frozenset({context.entry, *nx.descendants(graph, context.entry)})
    return tuple(arc for arc in arcs if arc[0] in reach)


def _dependence(
    graph: nx.DiGraph[str], arcs: tuple[Arc, ...], context: Context
) -> Mapping[str, tuple[Parent, ...]]:
    """Control dependence from post-dominators: an arc ``a -> b`` makes every node
    from ``b`` up the post-dominator tree, short of ``a``'s immediate
    post-dominator, depend on it. The entry depends on a synthetic start."""
    reverse = _with_exit(graph, context).reverse(copy=True)
    post = nx.immediate_dominators(reverse, EXIT)
    every = (*arcs, (START, context.entry, EdgeKind.FLOW))
    pairs = sorted(
        (
            (node, (source, kind))
            for source, target, kind in every
            if post[source] != target
            for node in _below(post, target, post[source])
        ),
        key=lambda pair: pair[0],
    )
    return {
        node: tuple(
            sorted(
                dict.fromkeys(parent for _, parent in group),
                key=lambda parent: (parent[0], parent[1].value),
            )
        )
        for node, group in groupby(pairs, key=lambda pair: pair[0])
    }


def _with_exit(graph: nx.DiGraph[str], context: Context) -> nx.DiGraph[str]:
    joined = graph.copy()
    ends = tuple(n for n in graph.nodes if graph.out_degree(n) == 0 or n == context.end)
    joined.add_edges_from((n, EXIT) for n in ends)
    joined.add_edge(START, context.entry)
    joined.add_edge(START, EXIT)
    stuck = frozenset(graph.nodes) - nx.ancestors(joined, EXIT)
    joined.add_edges_from((n, EXIT) for n in stuck)
    return joined


def _below(post: Mapping[str, str], node: str, stop: str) -> tuple[str, ...]:
    if node in (stop, EXIT):
        return ()
    return (node, *_below(post, post[node], stop))


@dataclass(frozen=True)
class Walk:
    """Enumerates ways lazily over each context's flow, built once per context."""

    program: Program
    flow: Callable[[Context], Flow]

    def chains(
        self, context: Context, target: str, active: frozenset[Context]
    ) -> Iterator[tuple[Decision, ...]]:
        """The decisions on a way from the context's entry to ``target``: a path
        of control dependences, then the decisions that bring back each PERFORM
        before ``target`` whose range can end the task."""
        flow = self.flow(context)
        returns = tuple(
            tuple(islice(self.chains(r, r.end, active | {r}), MAX_WAYS + 1))
            for r in self._ending(flow, target)
            if r not in active
        )
        return (
            (*chain, *(d for inserted in rest for d in inserted))
            for chain in self._dependences(flow, target, frozenset({target}))
            for rest in product(*returns)
        )

    def _dependences(
        self, flow: Flow, node: str, seen: frozenset[str]
    ) -> Iterator[tuple[Decision, ...]]:
        return (
            chain
            for source, kind in flow.parents.get(node, ())
            if source not in seen
            for chain in self._through(flow, source, kind, seen)
        )

    def _through(
        self, flow: Flow, source: str, kind: EdgeKind, seen: frozenset[str]
    ) -> Iterator[tuple[Decision, ...]]:
        if source == START:
            return iter(((),))
        decided = self._decision(source, kind)
        return (
            (*prefix, *decided)
            for prefix in self._dependences(flow, source, seen | {source})
        )

    def _decision(self, source: str, kind: EdgeKind) -> tuple[Decision, ...]:
        node = self.program.cfg.node(source)
        if node.kind is not NodeKind.TEST or kind not in DECIDING:
            return ()
        return (Decision(source, DECIDING[kind]),)

    def _ending(self, flow: Flow, target: str) -> tuple[Context, ...]:
        cfg = self.program.cfg
        ranges = tuple(
            performed(cfg, edge)
            for node in flow.dominated(target)
            for edge in perform_edge(cfg, node)
        )
        return tuple(r for r in ranges if self._can_end(r))

    def _can_end(self, range_: Context) -> bool:
        return bool(self.flow(range_).exits() - {range_.end})

    def ways(self, node: str, active: frozenset[Context]) -> Iterator[Way]:
        return (
            way
            for context in contexts(self.program.cfg)
            if context not in active and node in self.flow(context).nodes
            for way in self._in(context, node, active | {context})
        )

    def _in(
        self, context: Context, node: str, active: frozenset[Context]
    ) -> Iterator[Way]:
        if not context.is_range:
            return (Way(chain, ()) for chain in self.chains(context, node, active))
        return (
            Way((*outer.decisions, *chain), (*outer.calls, (context, call)))
            for call in entries_of(self.program.cfg, context).calls
            for outer in self.ways(call, active)
            for chain in self.chains(context, node, active)
        )


def ways_to(program: Program, node: str) -> Ways:
    cut = unfollowed(program)

    @cache
    def flow(context: Context) -> Flow:
        return flow_of(program, context, cut)

    walk = Walk(program, flow)
    found = tuple(islice(walk.ways(node, frozenset()), MAX_WAYS + 1))
    unique = tuple(dict.fromkeys(found))
    logger.info("%s: %d ways", node, len(unique))
    return Ways(unique[:MAX_WAYS], len(found) > MAX_WAYS)
