"""Resolve what some bytes hold at one node, walking back to received, returned and retrieved bytes."""

from collections.abc import Callable
from dataclasses import replace
from functools import partial, reduce

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution, joined
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.combine.walk import walked
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind

_LINKAGE = "linkage"
_CALLS = frozenset({JumpKind.LINK, JumpKind.CALL})
_WRITER_EXPLAINED = frozenset(
    {
        UnresolvedReason.NOT_A_LITERAL,
        UnresolvedReason.FROM_CALLEE,
        UnresolvedReason.FROM_FILE,
    }
)
Resolve = Callable[[ProgramTables, str, ByteRange], Resolution]
Vertex = tuple[str, ByteRange]
Step = tuple[Resolution, tuple[Vertex, ...]]


def resolve(tables: ProgramTables, node: str, at: ByteRange) -> Resolution:
    return walked((node, at), partial(step, tables), joined, Resolution()).found


def _unknown_stop(reasons: tuple[UnresolvedReason, ...]) -> Resolution:
    if not reasons:
        return Resolution()
    return Resolution(stops=frozenset({Stop(StopKind.UNKNOWN, reasons=reasons)}))


def _overlap(a: ByteRange, b: ByteRange) -> ByteRange:
    return replace(a, start=max(a.start, b.start), end=min(a.end, b.end))


def _stepped(left: Step, right: Step) -> Step:
    return joined(left[0], right[0]), left[1] + right[1]


def step(tables: ProgramTables, vertex: Vertex) -> Step:
    node, at = vertex
    facts = tables.facts_at(node, at)
    if not facts:
        return _unknown_stop((UnresolvedReason.NOT_RECORDED,)), ()
    return reduce(
        _stepped,
        (_from_fact(tables, at, where, fact) for where, fact in facts),
        (Resolution(), ()),
    )


def _sliced(fact: Fact, where: ByteRange, part: ByteRange) -> frozenset[str]:
    lo, hi = part.start - where.start, part.end - where.start
    return frozenset(value[lo:hi] for value in fact.values)


def _from_fact(
    tables: ProgramTables, at: ByteRange, where: ByteRange, fact: Fact
) -> Step:
    part = _overlap(at, where)
    values = Resolution(values=_sliced(fact, where, part))
    return reduce(
        _stepped,
        (
            _through(tables, writer, flow, part, fact)
            for writer in fact.writers
            for flow in tables.flows.get(writer, ())
            if flow.target.overlaps(part)
        ),
        (joined(values, _path_history(tables, part, fact)), ()),
    )


def _explained(reason: UnresolvedReason, part: ByteRange, fact: Fact) -> bool:
    if not fact.writers:
        return False
    if reason in _WRITER_EXPLAINED:
        return True
    return reason is UnresolvedReason.INBOUND_LINKAGE and part.region != _LINKAGE


def _path_history(tables: ProgramTables, part: ByteRange, fact: Fact) -> Resolution:
    reasons = tuple(r for r in fact.reasons if not _explained(r, part, fact))
    received = part.region == _LINKAGE and (
        UnresolvedReason.INBOUND_LINKAGE in reasons or not (fact.writers or fact.values)
    )
    if not received:
        return _unknown_stop(reasons)
    return joined(
        _received(tables, part),
        _unknown_stop(
            tuple(r for r in reasons if r is not UnresolvedReason.INBOUND_LINKAGE)
        ),
    )


def _received(tables: ProgramTables, part: ByteRange) -> Resolution:
    params = tables.received_param(part)
    if not params:
        return _unknown_stop((UnresolvedReason.INBOUND_LINKAGE,))
    return Resolution(
        stops=frozenset({Stop(StopKind.RECEIVED, at=part, param=params[0])})
    )


def _unknown(fact: Fact) -> Resolution:
    return _unknown_stop(tuple(r for r in fact.reasons if r in _WRITER_EXPLAINED))


def _through(
    tables: ProgramTables,
    writer: str,
    flow: Flow,
    part: ByteRange,
    fact: Fact,
) -> Step:
    written = _overlap(part, flow.target)
    if not flow.source.known:
        return _synthetic(tables, writer, written, fact), ()
    offset = flow.source.start - flow.target.start
    source = replace(
        flow.source,
        start=written.start + offset,
        end=min(flow.source.end, written.end + offset),
    )
    if source.start >= source.end:
        return Resolution(), ()
    return Resolution(), ((writer, source),)


def _synthetic(
    tables: ProgramTables, writer: str, written: ByteRange, fact: Fact
) -> Resolution:
    if writer not in tables.jumps:
        return _unknown(fact)
    return _at_jump(tables, tables.jumps[writer], written, fact)


def _at_jump(
    tables: ProgramTables, jump: Jump, written: ByteRange, fact: Fact
) -> Resolution:
    if jump.kind in _CALLS:
        return _returned(tables, jump, written, fact)
    if jump.kind is JumpKind.RETRIEVE:
        return Resolution(
            stops=frozenset({Stop(StopKind.RETRIEVED, at=written, node=jump.node)})
        )
    return _unknown(fact)


def _returned(
    tables: ProgramTables, jump: Jump, written: ByteRange, fact: Fact
) -> Resolution:
    params = tuple(
        area.param
        for area in jump.areas
        if byte_range(area.extent, tables.program).covers(written)
    )[:1]
    if not params:
        return _unknown(fact)
    return Resolution(
        stops=frozenset(
            {Stop(StopKind.RETURNED, at=written, node=jump.node, param=params[0])}
        )
    )
