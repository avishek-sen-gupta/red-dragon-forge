"""A demand carried backward over a program's writes: the ranges each node can still need."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate, repeat
from types import MappingProxyType

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.transfer import Statement, Write, writes_of
from cobble.dataflow.fixpoint.demand import Demand
from cobble.dataflow.fixpoint.live import Live, spans_of
from cobble.dataflow.srccfg.cfg import Cfg
from cobol_memory.field_extent import FieldExtent, Precision


@dataclass(frozen=True)
class _Backward:
    """Live ranges on entry to each node so far, and the node positions to revisit."""

    entry: Mapping[str, frozenset[FieldExtent]]
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
    cfg: Cfg, node: str, entry: Mapping[str, frozenset[FieldExtent]]
) -> frozenset[FieldExtent]:
    return frozenset(one for edge in cfg.successors(node) for one in entry[edge.target])


def _step(
    cfg: Cfg,
    order: tuple[str, ...],
    rank: Mapping[str, int],
    writes: Mapping[str, tuple[Write, ...]],
    demand: Demand,
    run: _Backward,
) -> _Backward:
    latest = max(run.queue)
    node = order[latest]
    now = entered(
        writes.get(node, ()),
        demand.at.get(node, frozenset()),
        _exiting(cfg, node, run.entry),
    )
    rest = run.queue - {latest}
    if now == run.entry[node]:
        return _Backward(entry=run.entry, queue=rest)
    return _Backward(
        entry=MappingProxyType({**run.entry, node: now}),
        queue=rest | {rank[edge.source] for edge in cfg.predecessors(node)},
    )


def _writes(
    cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex
) -> Mapping[str, tuple[Write, ...]]:
    return MappingProxyType(
        {
            node.id: writes_of(statements[node.id], node.id, index)
            for node in cfg.nodes
            if node.id in statements
        }
    )


def live(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    demand: Demand,
) -> Live:
    order = tuple(node.id for node in cfg.nodes)
    rank = MappingProxyType({one: position for position, one in enumerate(order)})
    writes = _writes(cfg, statements, index)
    start = _Backward(
        entry=MappingProxyType(
            {node: demand.at.get(node, frozenset()) for node in order}
        ),
        queue=frozenset(range(len(order))),
    )
    steps: Iterable[_Backward] = accumulate(
        repeat(None),
        lambda run, _: _step(cfg, order, rank, writes, demand, run),
        initial=start,
    )
    settled = next(run for run in steps if not run.queue)
    return Live(
        entry=MappingProxyType(
            {node: spans_of(ranges) for node, ranges in settled.entry.items()}
        )
    )
