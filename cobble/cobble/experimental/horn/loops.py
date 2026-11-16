"""The loops of each context's CFG: a loop with one entry node keeps its body and is cut at that header, whose state is the one the loop was entered in, freed wherever the loop or a range it performs may write; a loop entered at several nodes is a knot, collapsed to one such state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import networkx as nx
from cobble.dataflow.srccfg.cfg import Edge, EdgeKind
from cobble.dataflow.srccfg.desugar import PERFORM_TRANSFER
from cobble.experimental.horn.context import Context, perform_edge, performed, steps
from cobble.experimental.horn.effects import KEPT, Effect, Freed, Kept
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.storage import EIBCALEN, Storage

LOOPED = Freed(-4)


@dataclass(frozen=True)
class Loop:
    """``effect`` frees the segment bytes and ``tail`` the state positions past
    them that a run around the loop may change."""

    nodes: frozenset[str]
    effect: Effect
    tail: frozenset[int]


@dataclass(frozen=True)
class Loops:
    """Per header, its loop, whose back edges are not followed; and the knots."""

    headers: Mapping[str, Loop]
    knots: tuple[Loop, ...]

    def back(self, source: str, target: str) -> bool:
        return target in self.headers and source in self.headers[target].nodes


@dataclass(frozen=True)
class Cycles:
    program: Program
    storage: Storage
    members: Mapping[Context, frozenset[str]]
    effects: Mapping[str, Effect]
    cut: frozenset[Edge]

    def arcs(self, context: Context) -> tuple[tuple[str, str], ...]:
        cfg = self.program.cfg
        members = self.members[context]
        return (
            *(
                (e.source, e.target)
                for n in sorted(members)
                for e in steps(cfg, context, n)
                if e not in self.cut
            ),
            *(
                (n, cfg.node(n).resume)
                for n in sorted(members)
                if perform_edge(cfg, n) and cfg.node(n).resume in members
            ),
        )

    def of(self, context: Context) -> Loops:
        graph: nx.DiGraph[str] = nx.DiGraph()
        graph.add_nodes_from(self.members[context])
        graph.add_edges_from(self.arcs(context))
        found = self._split(graph, context.entry)
        return Loops(
            {header: self._loop(nodes) for header, nodes in found if header},
            tuple(self._loop(nodes) for header, nodes in found if not header),
        )

    def _split(
        self, graph: nx.DiGraph[str], entry: str
    ) -> tuple[tuple[str, frozenset[str]], ...]:
        """Each loop as its header and nodes, a knot with no header, inner loops
        found once the header's back edges are gone."""
        return tuple(
            found
            for component in _cycles(graph)
            for found in self._parts(graph, frozenset(component), entry)
        )

    def _parts(
        self, graph: nx.DiGraph[str], nodes: frozenset[str], entry: str
    ) -> tuple[tuple[str, frozenset[str]], ...]:
        entries = sorted(
            n
            for n in nodes
            if n == entry or any(p not in nodes for p in graph.predecessors(n))
        )
        if len(entries) != 1:
            return (("", nodes),)
        header = entries[0]
        inner: nx.DiGraph[str] = nx.DiGraph(graph.subgraph(nodes))
        inner.remove_edges_from(tuple(inner.in_edges(header)))
        return ((header, nodes), *self._split(inner, header))

    def _loop(self, nodes: frozenset[str]) -> Loop:
        closure = self._closure(nodes, frozenset())
        return Loop(nodes, self._effect(closure), self._tail(closure))

    def _closure(
        self, nodes: frozenset[str], seen: frozenset[Context]
    ) -> frozenset[str]:
        """``nodes``, and every node of each range a PERFORM among them enters."""
        cfg = self.program.cfg
        ranges = (
            frozenset(
                performed(cfg, edge) for n in nodes for edge in perform_edge(cfg, n)
            )
            - seen
        )
        inner = frozenset(
            node
            for range_ in ranges
            for node in self._closure(self.members[range_], seen | ranges)
        )
        return nodes | inner

    def _effect(self, closure: frozenset[str]) -> Effect:
        cfg = self.program.cfg
        unresolved = any(
            cfg.node(n).transfer == PERFORM_TRANSFER
            and any(e.kind is EdgeKind.FLOW for e in cfg.successors(n))
            for n in closure
        )
        return Effect(
            tuple(
                tuple(
                    (
                        LOOPED
                        if unresolved
                        or any(
                            not isinstance(self.effects[n].bytes[s][b], Kept)
                            for n in closure
                        )
                        else KEPT
                    )
                    for b in range(segment.length)
                )
                for s, segment in enumerate(self.storage.segments)
            )
        )

    def _tail(self, closure: frozenset[str]) -> frozenset[int]:
        storage, cfg = self.storage, self.program.cfg
        base = len(storage.segments)
        calen = (
            (base,)
            if storage.eib and any(EIBCALEN in cfg.node(n).writes for n in closure)
            else ()
        )
        first = base + int(storage.eib)
        marks = tuple(
            first + k
            for k, mark in enumerate(storage.marks)
            if mark.program == cfg.program and mark.node in closure
        )
        outcomes = first + len(storage.marks)
        tests = tuple(
            outcomes + k for k, test in enumerate(storage.outcomes) if test in closure
        )
        entered = frozenset(
            performed(cfg, edge) for n in closure for edge in perform_edge(cfg, n)
        )
        entries = tuple(
            outcomes + len(storage.outcomes) + k
            for k, e in enumerate(storage.entries)
            if e.range in entered
        )
        return frozenset((*calen, *marks, *tests, *entries))


def _cycles(graph: nx.DiGraph[str]) -> Iterable[set[str]]:
    return sorted(
        (
            component
            for component in nx.strongly_connected_components(graph)
            if len(component) > 1 or any(graph.has_edge(n, n) for n in component)
        ),
        key=sorted,
    )
