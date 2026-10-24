"""Fields of different programs that hold the same datum: every byte of one lands, in place, on every byte of the other."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

import networkx as nx
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind

logger = logging.getLogger(__name__)

_Byte = tuple[str, int]


@dataclass(frozen=True)
class _Bytes:
    """Where each byte moves, the moves out of relaying table occurrences and dataset slots, and every field's program and size."""

    moves: Mapping[_Byte, tuple[_Byte, ...]]
    relays: Set[str]
    relayed: nx.DiGraph[_Byte]
    fields: Mapping[str, GraphNode]


def _byte_moves(edges: Iterable[GraphEdge]) -> Mapping[_Byte, tuple[_Byte, ...]]:
    steps = sorted(
        ((edge.source, placed.source + k), (edge.target, placed.target + k))
        for edge in edges
        for placed in edge.alignments
        for k in range(placed.length)
    )
    return {
        byte: tuple(step for _, step in group)
        for byte, group in groupby(steps, itemgetter(0))
    }


def _read_back(edge: GraphEdge) -> GraphEdge:
    return edge.model_copy(
        update={
            "source": edge.target,
            "target": edge.source,
            "alignments": tuple(
                placed.model_copy(
                    update={"source": placed.target, "target": placed.source}
                )
                for placed in edge.alignments
            ),
        }
    )


def _unplaced(graph: FieldGraph, fields: Mapping[str, GraphNode]) -> frozenset[str]:
    return frozenset(
        edge.target
        for edge in graph.edges
        if not edge.aligned and edge.source in fields and edge.target in fields
    )


def _bytes(graph: FieldGraph) -> _Bytes:
    fields = {node.id: node for node in graph.nodes if node.kind is NodeKind.FIELD}
    slots = frozenset(node.id for node in graph.nodes if node.kind is NodeKind.DATASET)
    ends = fields.keys() | slots
    unplaced = _unplaced(graph, fields)
    placed = tuple(
        edge
        for edge in graph.edges
        if edge.aligned
        and edge.source in ends
        and edge.target in ends
        and edge.target not in unplaced
    )
    moves = _byte_moves(
        (*placed, *(_read_back(edge) for edge in placed if edge.source in slots))
    )
    relays = slots | {node for node, field in fields.items() if field.subscripts}
    relayed: nx.DiGraph[_Byte] = nx.DiGraph()
    relayed.add_edges_from(
        (start, end)
        for start, ends in moves.items()
        if start[0] in relays - unplaced
        for end in ends
    )
    return _Bytes(
        moves=moves,
        relays=relays - unplaced,
        relayed=relayed,
        fields={node: field for node, field in fields.items() if node not in unplaced},
    )


def _onward(found: _Bytes, byte: _Byte) -> frozenset[_Byte]:
    if byte[0] not in found.relays or byte not in found.relayed:
        return frozenset({byte})
    return frozenset({byte}) | frozenset(nx.descendants(found.relayed, byte))


def _landings(found: _Bytes, byte: _Byte) -> frozenset[_Byte]:
    return frozenset(
        end
        for step in found.moves.get(byte, ())
        for end in _onward(found, step)
        if end[0] not in found.relays and end[0] in found.fields
    )


def _exact(
    source: GraphNode, target: GraphNode, landed: Iterable[frozenset[_Byte]]
) -> bool:
    return source.size == target.size and all(
        {offset for node, offset in bytes_ if node == target.id} == {i}
        for i, bytes_ in enumerate(landed)
    )


def _partners(found: _Bytes, source: GraphNode) -> tuple[tuple[str, str], ...]:
    landed = tuple(_landings(found, (source.id, i)) for i in range(source.size))
    targets = {
        node
        for bytes_ in landed
        for node, _ in bytes_
        if found.fields[node].program != source.program
    }
    return tuple(
        (source.id, target)
        for target in sorted(targets)
        if _exact(source, found.fields[target], landed)
    )


def exact_classes(graph: FieldGraph) -> tuple[tuple[str, ...], ...]:
    found = _bytes(graph)
    sources = tuple(
        field
        for node, field in sorted(found.fields.items())
        if node not in found.relays and field.size > 0
    )
    pairs = tuple(pair for source in sources for pair in _partners(found, source))
    joined: nx.Graph[str] = nx.Graph()
    joined.add_edges_from(pairs)
    classes = tuple(
        sorted(
            tuple(sorted(component)) for component in nx.connected_components(joined)
        )
    )
    logger.info(
        "aggregate unify: %d exact pairs across programs, %d classes",
        len(pairs),
        len(classes),
    )
    return classes
