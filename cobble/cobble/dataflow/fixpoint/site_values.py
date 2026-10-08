"""The values a dynamic site's program operand can hold, by reaching definitions within its program."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import reduce
from itertools import accumulate, repeat

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.transfer import Statement, Write, writes_of
from cobble.dataflow.fields.values import (
    EMPTY,
    UnresolvedReason,
    ValueSet,
    because,
    merged,
)
from cobble.dataflow.srccfg.cfg import Cfg
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

_UNKNOWN = because(UnresolvedReason.NOT_A_LITERAL)


@dataclass(frozen=True)
class _Forward:
    """The values leaving each node position so far, and the positions to revisit."""

    out: tuple[ValueSet, ...]
    queue: frozenset[int]


@dataclass(frozen=True)
class SiteGraph:
    """The CFG as positions, and every write at each."""

    order: tuple[str, ...]
    successors: tuple[tuple[int, ...], ...]
    predecessors: tuple[tuple[int, ...], ...]
    writes: tuple[tuple[Write, ...], ...]
    entry: int


def _overlapping(one: FieldExtent, other: FieldExtent) -> bool:
    return (
        one.region is other.region and one.start < other.end and other.start < one.end
    )


def site_graph(
    cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex, entry: str
) -> SiteGraph:
    """The CFG once per program, each node with every write its statement makes."""
    order = tuple(node.id for node in cfg.nodes)
    rank = {node: position for position, node in enumerate(order)}
    return SiteGraph(
        order=order,
        successors=tuple(
            tuple(rank[edge.target] for edge in cfg.successors(node)) for node in order
        ),
        predecessors=tuple(
            tuple(rank[edge.source] for edge in cfg.predecessors(node))
            for node in order
        ),
        writes=tuple(
            writes_of(statements[node], node, index) if node in statements else ()
            for node in order
        ),
        entry=rank[entry],
    )


def _sliced(values: ValueSet, outer: FieldExtent, operand: FieldExtent) -> ValueSet:
    at = operand.start - outer.start
    return ValueSet(
        values=frozenset(value[at : at + operand.length] for value in values.values)
    )


def _replaces(write: Write, operand: FieldExtent) -> bool:
    """A write that must overwrite every byte of the operand with values it names."""
    target = write.target
    return (
        not write.weak
        and target.precision is Precision.EXACT
        and target.start <= operand.start
        and operand.end <= target.end
        and write.values.complete
        and bool(write.values.values)
    )


def _after(held: ValueSet, write: Write, operand: FieldExtent) -> ValueSet:
    if not _overlapping(write.target, operand):
        return held
    if _replaces(write, operand):
        return _sliced(write.values, write.target, operand)
    return _UNKNOWN


def _through(held: ValueSet, writes: Iterable[Write], operand: FieldExtent) -> ValueSet:
    return reduce(lambda now, write: _after(now, write, operand), writes, held)


def _arriving(
    graph: SiteGraph, run: _Forward, position: int, initial: ValueSet
) -> ValueSet:
    start = initial if position == graph.entry else EMPTY
    return reduce(
        merged, (run.out[before] for before in graph.predecessors[position]), start
    )


def _step(
    graph: SiteGraph, operand: FieldExtent, initial: ValueSet, run: _Forward
) -> _Forward:
    position = min(run.queue)
    now = _through(
        _arriving(graph, run, position, initial), graph.writes[position], operand
    )
    rest = run.queue - {position}
    if now == run.out[position]:
        return _Forward(out=run.out, queue=rest)
    return _Forward(
        out=(*run.out[:position], now, *run.out[position + 1 :]),
        queue=rest | frozenset(graph.successors[position]),
    )


def _initial(image: Mapping[FieldExtent, ValueSet], operand: FieldExtent) -> ValueSet:
    """What the operand holds when the program starts: a VALUE clause covering it,
    or nothing this program can name -- LINKAGE always."""
    if operand.region is RegionId.LINKAGE:
        return because(UnresolvedReason.INBOUND_LINKAGE)
    covering = tuple(
        extent
        for extent in image
        if extent.start <= operand.start
        and operand.end <= extent.end
        and extent.region is operand.region
    )
    if not covering:
        return because(UnresolvedReason.UNINITIALISED)
    return _sliced(image[covering[0]], covering[0], operand)


def values_at(
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    site: str,
    operand: FieldExtent,
) -> ValueSet:
    """The values ``operand`` can hold on reaching ``site``, complete only when
    every definition reaching it is a literal that overwrites all of it."""
    initial = _initial(image, operand)
    start = _Forward(
        out=tuple(EMPTY for _ in graph.order),
        queue=frozenset(range(len(graph.order))),
    )
    settled = next(
        run
        for run in accumulate(
            repeat(None),
            lambda run, _: _step(graph, operand, initial, run),
            initial=start,
        )
        if not run.queue
    )
    return _arriving(graph, settled, graph.order.index(site), initial)
