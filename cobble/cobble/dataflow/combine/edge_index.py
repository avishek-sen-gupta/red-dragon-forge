"""EdgeIndex — one round's edges, looked up by what each stop follows instead of scanned."""

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter
from types import MappingProxyType
from typing import TypeVar

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.jumps.jump_kind import JumpKind

_ENTERING = frozenset(
    {JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL, JumpKind.RETURN_TRANSID}
)
_K = TypeVar("_K", bound=Hashable)


@dataclass(frozen=True)
class EdgeIndex:
    into: Mapping[tuple[str, int], tuple[Edge, ...]]
    out: Mapping[tuple[str, str, int], tuple[Edge, ...]]
    started: Mapping[tuple[str, str], tuple[Edge, ...]]


def _grouped(
    edges: tuple[Edge, ...], place: Callable[[Edge], tuple[_K, ...]]
) -> Mapping[_K, tuple[Edge, ...]]:
    pairs = sorted((where, n) for n, edge in enumerate(edges) for where in place(edge))
    return MappingProxyType(
        {
            where: tuple(edges[n] for _, n in group)
            for where, group in groupby(pairs, itemgetter(0))
        }
    )


def _into(edge: Edge) -> tuple[tuple[str, int], ...]:
    return ((edge.callee, edge.param),) if edge.kind in _ENTERING else ()


def _out(edge: Edge) -> tuple[tuple[str, str, int], ...]:
    return ((edge.caller, edge.node, edge.param),)


def _started(edge: Edge) -> tuple[tuple[str, str], ...]:
    return ((edge.callee, edge.callee_node),) if edge.kind is JumpKind.START else ()


def edge_index(edges: frozenset[Edge]) -> EdgeIndex:
    ordered = tuple(edges)
    return EdgeIndex(
        _grouped(ordered, _into), _grouped(ordered, _out), _grouped(ordered, _started)
    )
