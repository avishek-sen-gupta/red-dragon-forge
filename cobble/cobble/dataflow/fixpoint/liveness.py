"""A demand carried backward over a program's writes: the ranges each node can still need."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate, repeat
from types import MappingProxyType

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.spans import spans_of
from cobble.dataflow.fields.transfer import Statement, Write, writes_of
from cobble.dataflow.fixpoint.demand import Demand
from cobble.dataflow.fixpoint.live import Live
from cobble.dataflow.fixpoint.live_graph import LiveGraph
from cobble.dataflow.srccfg.cfg import Cfg
from cobol_memory.field_extent import FieldExtent, Precision


@dataclass(frozen=True)
class _Backward:
    """Live ranges on entry to each node position so far, and the positions to revisit."""

    entry: tuple[frozenset[FieldExtent], ...]
    queue: frozenset[int]


def _overlap(left: FieldExtent, right: FieldExtent) -> bool:
    return (
        left.region is right.region
        and left.start < right.end
        and right.start < left.end
    )


def _strong(write: Write) -> bool:
    return not write.weak and write.target.precision is Precision.EXACT


def entered(
    writes: Sequence[Write],
    demanded: frozenset[FieldExtent],
    exiting: frozenset[FieldExtent],
) -> frozenset[FieldExtent]:
    touching = tuple(
        write for write in writes if any(_overlap(write.target, one) for one in exiting)
    )
    killers = tuple(write.target for write in writes if _strong(write))
    return (
        demanded
        | frozenset(
            one
            for one in exiting
            if not any(target.must_cover(one) for target in killers)
        )
        | frozenset(
            source.extent
            for write in touching
            for source in write.sources
            if not source.origin
        )
        | frozenset(write.target for write in touching if not _strong(write))
    )


def _exiting(
    graph: LiveGraph, position: int, entry: tuple[frozenset[FieldExtent], ...]
) -> frozenset[FieldExtent]:
    return frozenset(
        one for successor in graph.successors[position] for one in entry[successor]
    )


def _step(graph: LiveGraph, demand: Demand, run: _Backward) -> _Backward:
    latest = max(run.queue)
    now = entered(
        graph.writes[latest],
        demand.at.get(graph.order[latest], frozenset()),
        _exiting(graph, latest, run.entry),
    )
    rest = run.queue - {latest}
    if now == run.entry[latest]:
        return _Backward(entry=run.entry, queue=rest)
    return _Backward(
        entry=(*run.entry[:latest], now, *run.entry[latest + 1 :]),
        queue=rest | frozenset(graph.predecessors[latest]),
    )


def graph_of(
    cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex
) -> LiveGraph:
    order = tuple(node.id for node in cfg.nodes)
    rank = {one: position for position, one in enumerate(order)}
    return LiveGraph(
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
    )


def live_sets(graph: LiveGraph, demand: Demand) -> tuple[frozenset[FieldExtent], ...]:
    """The ranges live on entry to each node, in ``graph.order``."""
    start = _Backward(
        entry=tuple(demand.at.get(node, frozenset()) for node in graph.order),
        queue=frozenset(range(len(graph.order))),
    )
    steps: Iterable[_Backward] = accumulate(
        repeat(None), lambda run, _: _step(graph, demand, run), initial=start
    )
    return next(run for run in steps if not run.queue).entry


def live(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    demand: Demand,
) -> Live:
    graph = graph_of(cfg, statements, index)
    return Live(
        entry=MappingProxyType(
            {
                node: spans_of(ranges)
                for node, ranges in zip(
                    graph.order, live_sets(graph, demand), strict=True
                )
            }
        )
    )
