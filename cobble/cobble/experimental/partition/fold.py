"""Folds each run of consecutive table occurrences that the page would draw alike into one drawn node."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import groupby

from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode

_Ends = tuple[str, ...]
_NONE: _Ends = ()
_Likeness = tuple[str, str, str, tuple[int, ...], int, _Ends, _Ends]


@dataclass(frozen=True)
class Folded:
    """The graph as drawn, and the occurrences behind each drawn node that folds several."""

    graph: FieldGraph
    occurrences: Mapping[str, tuple[GraphNode, ...]]


def _likeness(node: GraphNode, component: int, into: _Ends, out: _Ends) -> _Likeness:
    return (
        node.program,
        node.record,
        node.field,
        node.subscripts[:-1],
        component,
        into,
        out,
    )


def _runs(ranked: Sequence[GraphNode]) -> tuple[tuple[GraphNode, ...], ...]:
    return tuple(
        tuple(node for _, node in run)
        for _, run in groupby(
            enumerate(ranked), lambda placed: placed[1].subscripts[-1] - placed[0]
        )
    )


def _span(run: Sequence[GraphNode], text: str) -> str:
    first, last = run[0].subscripts, run[-1].subscripts
    lanes = (*(str(i) for i in first[:-1]), f"{first[-1]}:{last[-1]}")
    return f"{text}({','.join(lanes)})"


def _drawn(run: Sequence[GraphNode]) -> GraphNode:
    head = run[0]
    return replace(
        head,
        id=_span(run, f"{head.program}:{head.record}.{head.field}"),
        label=_span(run, f"{head.program}.{head.field}"),
    )


def _merged(ends: tuple[str, str], edges: Iterable[GraphEdge]) -> GraphEdge:
    taken = tuple(edges)
    return replace(
        taken[0],
        source=ends[0],
        target=ends[1],
        sites=max(edge.sites for edge in taken),
        clustered=any(edge.clustered for edge in taken),
        cross_program=any(edge.cross_program for edge in taken),
    )


def _neighbours(pairs: Iterable[tuple[str, str]]) -> Mapping[str, _Ends]:
    return {
        end: tuple(other for _, other in group)
        for end, group in groupby(sorted(pairs), lambda pair: pair[0])
    }


def _folds(
    graph: FieldGraph, component_of: Mapping[str, int]
) -> tuple[tuple[GraphNode, ...], ...]:
    into = _neighbours((edge.target, edge.source) for edge in graph.edges)
    out = _neighbours((edge.source, edge.target) for edge in graph.edges)
    alike = sorted(
        (
            _likeness(
                node,
                component_of.get(node.id, -1),
                into.get(node.id, _NONE),
                out.get(node.id, _NONE),
            ),
            node.subscripts[-1],
            node.id,
            node,
        )
        for node in graph.nodes
        if node.subscripts
    )
    return tuple(
        run
        for _, group in groupby(alike, lambda entry: entry[0])
        for run in _runs(tuple(entry[-1] for entry in group))
        if len(run) > 1
    )


def folded(graph: FieldGraph, component_of: Mapping[str, int]) -> Folded:
    runs = tuple((_drawn(run), run) for run in _folds(graph, component_of))
    renamed = {node.id: drawn.id for drawn, run in runs for node in run}
    kept = tuple(node for node in graph.nodes if node.id not in renamed)
    ends = sorted(
        (
            (
                renamed.get(edge.source, edge.source),
                renamed.get(edge.target, edge.target),
            ),
            place,
            edge,
        )
        for place, edge in enumerate(graph.edges)
    )
    grouped = sorted(
        (min(entry[1] for entry in taken), pair, tuple(entry[-1] for entry in taken))
        for pair, group in groupby(ends, lambda entry: entry[0])
        for taken in (tuple(group),)
    )
    return Folded(
        graph=FieldGraph(
            nodes=(*kept, *(drawn for drawn, _ in runs)),
            edges=tuple(_merged(pair, edges) for _, pair, edges in grouped),
        ),
        occurrences={drawn.id: run for drawn, run in runs},
    )
