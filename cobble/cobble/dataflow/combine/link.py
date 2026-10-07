"""Link programs: values cross programs over a call graph grown from those values, in rounds."""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import partial, reduce
from types import MappingProxyType

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.held import Held, held_join
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolve import Resolve, resolve
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.combine.walk import walked
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.targets import ResolvedTarget, is_program_name
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind

logger = logging.getLogger(__name__)

_ENTERING = frozenset(
    {JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL, JumpKind.RETURN_TRANSID}
)
_NAMED = frozenset({JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL})
_OUTSIDE = Held(reasons=frozenset({UnresolvedReason.OUTSIDE_ANALYSED_SET}))
_INBOUND = Held(reasons=frozenset({UnresolvedReason.INBOUND_LINKAGE}))
_FROM_CALLEE = Held(reasons=frozenset({UnresolvedReason.FROM_CALLEE}))
_NOT_A_LITERAL = Held(reasons=frozenset({UnresolvedReason.NOT_A_LITERAL}))
_Vertex = tuple[str, str, ByteRange]
_Expansion = tuple[Held, tuple[_Vertex, ...]]
_Start = tuple[str, str, Fact]
_EdgeOrder = tuple[str, str, str, int, str, str, int, int, str, int, int, bool]


@dataclass(frozen=True)
class _World:
    tables: Mapping[str, ProgramTables]
    edges: frozenset[Edge]
    outside: OutsideJumps
    areas: CalleeAreas
    transactions: Mapping[str, str]
    resolver: Resolve
    answers: Mapping[_Start, Held] = MappingProxyType({})


_Follow = Callable[[_World, str, Stop], _Expansion]
_Callees = Callable[[_World, str, Jump], tuple[tuple[str, bool], ...]]


def link(
    tables: Mapping[str, ProgramTables],
    areas: CalleeAreas,
    transactions: Mapping[str, str],
    outside: OutsideJumps,
    resolver: Resolve = resolve,
) -> Linked:
    world = _World(tables, frozenset(), outside, areas, transactions, resolver)
    return _rounds(_answered_in(world), 1)


def _rounds(world: _World, round_: int) -> Linked:
    found = frozenset(_edges(world))
    new = found - world.edges
    logger.info(
        "combine:   round %d, %d edges total, %d new, %d programs",
        round_,
        len(found),
        len(new),
        len(world.tables),
    )
    if found <= world.edges:
        return _linked(world, round_)
    return _rounds(_answered_in(replace(world, edges=world.edges | found)), round_ + 1)


def _program_answers(
    world: _World,
    program: str,
    tables: ProgramTables,
) -> tuple[tuple[_Start, Held], ...]:
    return tuple(
        ((program, jump.node, fact), _fact_held(world, program, jump.node, fact))
        for jump in tables.jumps.values()
        for fact in (jump.target, jump.transid)
    )


def _collect_answers(
    world: _World,
    items: tuple[tuple[str, ProgramTables], ...],
    index: int,
    started: float,
    last_log: float,
) -> tuple[tuple[_Start, Held], ...]:
    if index >= len(items):
        return ()
    program, tables = items[index]
    batch = _program_answers(world, program, tables)
    now = time.monotonic()
    if now - last_log >= 5.0:
        logger.info(
            "combine:   answering %s [%d/%d] programs (%.1fs)",
            program,
            index + 1,
            len(items),
            now - started,
        )
        return batch + _collect_answers(world, items, index + 1, started, now)
    return batch + _collect_answers(world, items, index + 1, started, last_log)


def _answered_in(world: _World) -> _World:
    total_programs = len(world.tables)
    total_jumps = sum(len(t.jumps) for t in world.tables.values())
    logger.info(
        "combine:   answering %d programs (%d jumps, %d edges)...",
        total_programs,
        total_jumps,
        len(world.edges),
    )
    started = time.monotonic()
    pairs = _collect_answers(world, tuple(world.tables.items()), 0, started, started)
    logger.info(
        "combine:   answered %d programs, %d jumps in %.1fs",
        total_programs,
        total_jumps,
        time.monotonic() - started,
    )
    return replace(world, answers=MappingProxyType(dict(pairs)))


def _answer(world: _World, program: str, node: str, fact: Fact) -> Held:
    return world.answers[(program, node, fact)]


def _names(values: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted({v.rstrip() for v in values if is_program_name(v.rstrip())}))


def _fact_held(world: _World, program: str, node: str, fact: Fact) -> Held:
    if not fact.extent:
        return Held(values=frozenset(fact.values), reasons=frozenset(fact.reasons))
    return _held(world, (program, node, byte_range(fact.extent, program)))


def _shifted(at: ByteRange, src: ByteRange, dst: ByteRange, program: str) -> ByteRange:
    start = max(at.start, src.start)
    end = min(at.end, src.end)
    return replace(
        dst,
        program=program,
        start=dst.start + start - src.start,
        end=dst.start + end - src.start,
    )


def _held(world: _World, start: _Vertex) -> Held:
    walk = walked(start, partial(_expanded, world), held_join, Held())
    return held_join(walk.found, Held(cycled=walk.revisited))


def _joined(left: _Expansion, right: _Expansion) -> _Expansion:
    return held_join(left[0], right[0]), left[1] + right[1]


def _ending(held: Held) -> _Expansion:
    return held, ()


def _expanded(world: _World, vertex: _Vertex) -> _Expansion:
    program, node, at = vertex
    found = world.resolver(world.tables[program], node, at)
    return reduce(
        _joined,
        (_FOLLOW[stop.kind](world, program, stop) for stop in found.stops),
        _ending(Held(values=found.values)),
    )


def _unknown(world: _World, program: str, stop: Stop) -> _Expansion:
    return _ending(Held(reasons=frozenset(stop.reasons)))


def _outside_callers(world: _World, program: str) -> Held:
    callers = world.outside.known_into.get(program, ())
    if not callers:
        return Held()
    return replace(_OUTSIDE, outside=frozenset(callers))


def _entering(edge: Edge, program: str, stop: Stop) -> bool:
    return (
        edge.callee == program and edge.kind in _ENTERING and edge.param == stop.param
    )


def _from_caller(edge: Edge, stop: Stop) -> _Expansion:
    if not edge.callee_window.covers(stop.at):
        return _ending(_INBOUND)
    at = _shifted(stop.at, edge.callee_window, edge.caller_window, edge.caller)
    if edge.named_by.covers(at):
        return _ending(Held(values=frozenset({_callee_name(edge, at)})))
    return Held(), ((edge.caller, edge.node, at),)


def _callee_name(edge: Edge, at: ByteRange) -> str:
    named = edge.named_by
    padded = edge.callee.ljust(named.length)
    return padded[at.start - named.start : at.end - named.start]


def _received(world: _World, program: str, stop: Stop) -> _Expansion:
    into = tuple(e for e in world.edges if _entering(e, program, stop))
    from_callers = reduce(
        _joined, (_from_caller(e, stop) for e in into), _ending(Held())
    )
    gaps = Held() if into else _INBOUND
    return _joined(
        from_callers, _ending(held_join(gaps, _outside_callers(world, program)))
    )


def _returned(world: _World, program: str, stop: Stop) -> _Expansion:
    out = tuple(
        e
        for e in world.edges
        if e.caller == program and e.node == stop.node and e.param == stop.param
    )
    if not out:
        return _ending(_FROM_CALLEE)
    return reduce(_joined, (_left_by(world, e, stop) for e in out), _ending(Held()))


def _left_by(world: _World, edge: Edge, stop: Stop) -> _Expansion:
    exits = _exits(world, edge.callee)
    if not exits or not edge.caller_window.covers(stop.at):
        return _ending(_FROM_CALLEE)
    at = _shifted(stop.at, edge.caller_window, edge.callee_window, edge.callee)
    return Held(), tuple((edge.callee, exit_.node, at) for exit_ in exits)


def _exits(world: _World, program: str) -> tuple[Jump, ...]:
    if program not in world.tables:
        return ()
    return tuple(
        j for j in world.tables[program].jumps.values() if j.kind is JumpKind.EXIT
    )


def _from_starter(edge: Edge, stop: Stop) -> _Expansion:
    if not edge.callee_window.covers(stop.at):
        return _ending(_NOT_A_LITERAL)
    at = _shifted(stop.at, edge.callee_window, edge.caller_window, edge.caller)
    return Held(), ((edge.caller, edge.node, at),)


def _retrieved(world: _World, program: str, stop: Stop) -> _Expansion:
    starts = tuple(
        e
        for e in world.edges
        if e.kind is JumpKind.START
        and e.callee == program
        and e.callee_node == stop.node
    )
    if not starts:
        return _ending(_NOT_A_LITERAL)
    return reduce(_joined, (_from_starter(e, stop) for e in starts), _ending(Held()))


_FOLLOW: Mapping[StopKind, _Follow] = {
    StopKind.UNKNOWN: _unknown,
    StopKind.RECEIVED: _received,
    StopKind.RETURNED: _returned,
    StopKind.RETRIEVED: _retrieved,
}


def _lined_up(caller: ByteRange, callee: ByteRange) -> tuple[ByteRange, ByteRange]:
    shared = min(caller.length, callee.length)
    return (
        replace(caller, end=caller.start + shared),
        replace(callee, end=callee.start + shared),
    )


def _edges(world: _World) -> tuple[Edge, ...]:
    return tuple(
        edge
        for program, tables in world.tables.items()
        for jump in tables.jumps.values()
        for edge in _jump_edges(world, program, jump)
    )


def _program_callees(
    world: _World, program: str, jump: Jump
) -> tuple[tuple[str, bool], ...]:
    own = frozenset(_names(frozenset(jump.target.values)))
    found = _names(_answer(world, program, jump.node, jump.target).values)
    return tuple((name, name not in own) for name in found)


def _transaction_callees(
    world: _World, program: str, jump: Jump
) -> tuple[tuple[str, bool], ...]:
    own = frozenset(_names(frozenset(jump.transid.values)))
    found = _names(_answer(world, program, jump.node, jump.transid).values)
    return tuple(
        (world.transactions[t], t not in own) for t in found if t in world.transactions
    )


def _no_callees(
    world: _World, program: str, jump: Jump
) -> tuple[tuple[str, bool], ...]:
    return ()


_CALLEES: Mapping[JumpKind, _Callees] = {
    JumpKind.XCTL: _program_callees,
    JumpKind.LINK: _program_callees,
    JumpKind.CALL: _program_callees,
    JumpKind.RETURN_TRANSID: _transaction_callees,
    JumpKind.START: _transaction_callees,
}


def _jump_edges(world: _World, program: str, jump: Jump) -> tuple[Edge, ...]:
    return tuple(
        edge
        for callee, discovered in _CALLEES.get(jump.kind, _no_callees)(
            world, program, jump
        )
        for area in jump.areas
        for edge in _area_edges(world, program, jump, callee, discovered, area)
    )


def _area_edges(
    world: _World,
    program: str,
    jump: Jump,
    callee: str,
    discovered: bool,
    area: JumpArea,
) -> tuple[Edge, ...]:
    if jump.kind is JumpKind.START:
        return _start_edges(world, program, jump, callee, discovered, area)
    return _entry_edges(world, program, jump, callee, discovered, area)


def _retrieves(world: _World, callee: str) -> tuple[Jump, ...]:
    if callee not in world.tables:
        return ()
    return tuple(
        r
        for r in world.tables[callee].jumps.values()
        if r.kind is JumpKind.RETRIEVE and r.areas
    )


def _start_edges(
    world: _World,
    program: str,
    jump: Jump,
    callee: str,
    discovered: bool,
    area: JumpArea,
) -> tuple[Edge, ...]:
    mine = byte_range(area.extent, program)
    return tuple(
        Edge(
            program,
            jump.node,
            jump.kind,
            callee,
            area.param,
            *_lined_up(mine, byte_range(r.areas[0].extent, callee)),
            callee_node=r.node,
            discovered=discovered,
        )
        for r in _retrieves(world, callee)
    )


def _entry_edges(
    world: _World,
    program: str,
    jump: Jump,
    callee: str,
    discovered: bool,
    area: JumpArea,
) -> tuple[Edge, ...]:
    kind = JumpKind.XCTL if jump.kind is JumpKind.RETURN_TRANSID else jump.kind
    received = world.areas.area(callee, kind, area.param)
    if not received.known:
        return ()
    mine, theirs = _lined_up(byte_range(area.extent, program), received)
    return (
        Edge(
            program,
            jump.node,
            jump.kind,
            callee,
            area.param,
            mine,
            theirs,
            discovered=discovered,
            named_by=_named_by(program, jump, mine),
        ),
    )


def _named_by(program: str, jump: Jump, mine: ByteRange) -> ByteRange:
    field = byte_range(jump.target.extent, program)
    if jump.kind not in _NAMED or not mine.covers(field):
        return NO_RANGE
    return field


def _sorted_reasons(
    reasons: frozenset[UnresolvedReason],
) -> tuple[UnresolvedReason, ...]:
    return tuple(r for _, r in sorted((r.value, r) for r in reasons))


def _answered(held: Held) -> Held:
    if held.values or held.reasons or not held.cycled:
        return held
    return held_join(held, _INBOUND)


def _target(world: _World, program: str, node: str) -> LinkedTarget:
    tables = world.tables[program]
    site = tables.sites[node]
    held = _answered(_answer(world, program, node, tables.jumps[node].target))
    names = _names(held.values)
    return LinkedTarget(
        ResolvedTarget(
            caller=program,
            node=node,
            transfer=site.transfer,
            expression=site.expression,
            candidates=names,
            reasons=_sorted_reasons(held.reasons),
            dropped=tuple(sorted({v.rstrip() for v in held.values} - set(names))),
        ),
        tuple(sorted(held.outside)),
    )


def _order(edge: Edge) -> _EdgeOrder:
    mine, theirs = edge.caller_window, edge.callee_window
    return (
        edge.caller,
        edge.node,
        edge.callee,
        edge.param,
        edge.callee_node,
        mine.region,
        mine.start,
        mine.end,
        theirs.region,
        theirs.start,
        theirs.end,
        edge.discovered,
    )


def _sorted_edges(edges: frozenset[Edge]) -> tuple[Edge, ...]:
    return tuple(
        e for _order_of, _n, e in sorted((_order(e), n, e) for n, e in enumerate(edges))
    )


def _linked(world: _World, rounds: int) -> Linked:
    return Linked(
        targets=tuple(
            _target(world, program, node)
            for program in sorted(world.tables)
            for node in sorted(world.tables[program].sites)
            if node in world.tables[program].jumps
        ),
        edges=_sorted_edges(world.edges),
        report=RunReport(
            rounds=rounds,
            discovered=sum(1 for e in world.edges if e.discovered),
            unresolved_outside_jumps=world.outside.unresolved,
            without_results=world.outside.without_results,
        ),
    )
