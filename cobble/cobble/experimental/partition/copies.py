"""Every place the bytes of one value are copied to or fed from, followed byte by byte."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby

from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind

_Byte = tuple[str, int, int]
_Move = tuple[str, int, int, int]
_Moves = Mapping[str, tuple[_Move, ...]]


class CopyWalkError(ValueError):
    """A start the walk cannot begin from."""


@dataclass(frozen=True, order=True)
class Copy:
    """``node`` holds every byte of the value, the first at offset ``base``."""

    node: str
    base: int


@dataclass(frozen=True)
class _Index:
    nodes: Mapping[str, GraphNode]
    forward: _Moves
    backward: _Moves
    width: int


def _grouped(moves: Iterable[tuple[str, _Move]]) -> _Moves:
    ordered = sorted(moves, key=lambda move: move[0])
    return {
        node: tuple(move for _, move in group)
        for node, group in groupby(ordered, key=lambda move: move[0])
    }


def _aliases(
    graph: FieldGraph, redefines: Mapping[tuple[str, str], str]
) -> tuple[tuple[str, _Move], ...]:
    by_name = {
        (node.program, node.field): node
        for node in graph.nodes
        if node.kind is NodeKind.FIELD and not node.subscripts
    }
    pairs = tuple(
        (by_name[key], by_name[(key[0], base)])
        for key, base in redefines.items()
        if key in by_name and (key[0], base) in by_name
    )
    return tuple(
        link
        for one, other in pairs
        for length in (min(one.size, other.size),)
        for link in (
            (one.id, (other.id, 0, 0, length)),
            (other.id, (one.id, 0, 0, length)),
        )
    )


def _index(
    graph: FieldGraph, redefines: Mapping[tuple[str, str], str], width: int
) -> _Index:
    copied = tuple(edge for edge in graph.edges if not edge.rebuilt)
    aliases = _aliases(graph, redefines)
    forward = tuple(
        (edge.source, (edge.target, a.source, a.target, a.length))
        for edge in copied
        for a in edge.alignments
    )
    backward = tuple(
        (edge.target, (edge.source, a.target, a.source, a.length))
        for edge in copied
        for a in edge.alignments
    )
    return _Index(
        nodes={node.id: node for node in graph.nodes},
        forward=_grouped((*forward, *aliases)),
        backward=_grouped((*backward, *aliases)),
        width=width,
    )


def _steps(
    moves: _Moves, admits: Callable[[str], bool]
) -> Callable[[_Byte], frozenset[_Byte]]:
    def step(byte: _Byte) -> frozenset[_Byte]:
        node, offset, start = byte
        return frozenset(
            (other, there + offset - here, start)
            for other, here, there, length in moves.get(node, ())
            if here <= offset < here + length and admits(other)
        )

    return step


def _closure(
    frontier: frozenset[_Byte],
    seen: frozenset[_Byte],
    step: Callable[[_Byte], frozenset[_Byte]],
) -> frozenset[_Byte]:
    if not frontier:
        return seen
    found = frozenset(byte for here in frontier for byte in step(here)) - seen
    return _closure(found, seen | found, step)


def _narrow(index: _Index) -> Callable[[str], bool]:
    return lambda node: index.nodes[node].size <= index.width


def _reached(index: _Index, seeds: frozenset[_Byte]) -> frozenset[_Byte]:
    narrow = _narrow(index)
    copied = _closure(seeds, seeds, _steps(index.forward, lambda _: True))
    fed = frozenset(byte for byte in copied if narrow(byte[0]))
    reached = copied | _closure(fed, fed, _steps(index.backward, narrow))
    slots = frozenset(
        byte for byte in reached if index.nodes[byte[0]].kind is NodeKind.DATASET
    )
    more = slots - seeds
    return _reached(index, seeds | more) if more else reached


def _checked(index: _Index, start: str) -> str:
    if start not in index.nodes:
        raise CopyWalkError(f"{start} is not a node of the graph")
    size = index.nodes[start].size
    if size < index.width:
        raise CopyWalkError(
            f"{start} holds {size} bytes, fewer than the width {index.width}"
        )
    return start


def _whole(index: _Index, reached: frozenset[_Byte]) -> tuple[Copy, ...]:
    placed = sorted((node, offset - start, start) for node, offset, start in reached)
    return tuple(
        Copy(node=node, base=base)
        for (node, base), group in groupby(placed, key=lambda byte: byte[:2])
        if len({byte[2] for byte in group}) == index.width
        and not (index.nodes[node].size == 1 and index.nodes[node].subscripts)
    )


def copies(
    graph: FieldGraph,
    redefines: Mapping[tuple[str, str], str],
    starts: Sequence[str],
    width: int,
) -> tuple[Copy, ...]:
    if width < 1:
        raise CopyWalkError(f"the width must be at least 1 byte, not {width}")
    index = _index(graph, redefines, width)
    seeds = frozenset(
        (_checked(index, start), byte, byte)
        for start in starts
        for byte in range(width)
    )
    return _whole(index, _reached(index, seeds))
