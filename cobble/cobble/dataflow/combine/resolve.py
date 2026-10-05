"""Resolve what some bytes hold at one node, walking back to received, returned and retrieved bytes."""

from dataclasses import replace
from functools import reduce

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution, joined
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind

_LINKAGE = "linkage"
_CALLS = frozenset({JumpKind.LINK, JumpKind.CALL})
_STRUCTURAL = frozenset(
    {UnresolvedReason.INBOUND_LINKAGE, UnresolvedReason.FROM_CALLEE}
)
_Seen = frozenset[tuple[str, str, int, int]]


def resolve(tables: ProgramTables, node: str, at: ByteRange) -> Resolution:
    facts = tables.facts_at(node, at)
    if not facts:
        return Resolution(
            stops=frozenset(
                {Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.NOT_RECORDED,))}
            )
        )
    return _from_facts(tables, node, at, facts, frozenset())


def _visit(node: str, at: ByteRange) -> tuple[str, str, int, int]:
    return (node, at.region, at.start, at.end)


def _overlap(a: ByteRange, b: ByteRange) -> ByteRange:
    return replace(a, start=max(a.start, b.start), end=min(a.end, b.end))


def _from_facts(
    tables: ProgramTables,
    node: str,
    at: ByteRange,
    facts: tuple[tuple[ByteRange, Fact], ...],
    seen: _Seen,
) -> Resolution:
    if _visit(node, at) in seen:
        return Resolution()
    inner = seen | {_visit(node, at)}
    return reduce(
        joined,
        (_from_fact(tables, at, where, fact, inner) for where, fact in facts),
        Resolution(),
    )


def _sliced(fact: Fact, where: ByteRange, part: ByteRange) -> frozenset[str]:
    lo, hi = part.start - where.start, part.end - where.start
    return frozenset(value[lo:hi] for value in fact.values)


def _from_fact(
    tables: ProgramTables, at: ByteRange, where: ByteRange, fact: Fact, seen: _Seen
) -> Resolution:
    part = _overlap(at, where)
    values = Resolution(values=_sliced(fact, where, part))
    if fact.writers:
        return reduce(
            joined,
            (
                _through(tables, writer, flow, part, fact, seen)
                for writer in fact.writers
                for flow in tables.flows.get(writer, ())
                if flow.target.overlaps(part)
            ),
            joined(values, _unsettled(fact)),
        )
    if part.region == _LINKAGE and not fact.values:
        return joined(values, _received(tables, part))
    return joined(values, _unknown(fact))


def _received(tables: ProgramTables, part: ByteRange) -> Resolution:
    params = tables.received_param(part)
    if not params:
        return Resolution(
            stops=frozenset(
                {Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.INBOUND_LINKAGE,))}
            )
        )
    return Resolution(
        stops=frozenset({Stop(StopKind.RECEIVED, at=part, param=params[0])})
    )


def _unknown(fact: Fact) -> Resolution:
    reasons = tuple(r for r in fact.reasons if r not in _STRUCTURAL)
    complete = fact.values and UnresolvedReason.INCOMPLETE_WALK not in reasons
    if complete or not reasons:
        return Resolution()
    return Resolution(stops=frozenset({Stop(StopKind.UNKNOWN, reasons=reasons)}))


def _unsettled(fact: Fact) -> Resolution:
    if UnresolvedReason.INCOMPLETE_WALK not in fact.reasons:
        return Resolution()
    return _unknown(fact)


def _through(
    tables: ProgramTables,
    writer: str,
    flow: Flow,
    part: ByteRange,
    fact: Fact,
    seen: _Seen,
) -> Resolution:
    written = _overlap(part, flow.target)
    if not flow.source.known:
        return _synthetic(tables, writer, written, fact)
    offset = flow.source.start - flow.target.start
    source = replace(
        flow.source,
        start=written.start + offset,
        end=min(flow.source.end, written.end + offset),
    )
    if source.start >= source.end:
        return Resolution()
    return _from_facts(tables, writer, source, tables.facts_at(writer, source), seen)


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
