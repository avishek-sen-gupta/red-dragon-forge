"""Link programs: values cross programs over a call graph grown from those values, in rounds."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import reduce

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.held import Held, held_join
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolve import resolve
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.targets import ResolvedTarget, is_program_name
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind

_ENTERING = frozenset(
    {JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL, JumpKind.RETURN_TRANSID}
)
_OUTSIDE = Held(reasons=frozenset({UnresolvedReason.OUTSIDE_ANALYSED_SET}))
_Visiting = frozenset[tuple[str, str, str, int, int]]
_EdgeOrder = tuple[str, str, str, int, str, str, int, int, str, int, int, bool]


@dataclass(frozen=True)
class _World:
    tables: Mapping[str, ProgramTables]
    edges: frozenset[Edge]
    outside: OutsideJumps
    areas: CalleeAreas
    transactions: Mapping[str, str]


_Follow = Callable[[_World, str, Stop, _Visiting], Held]
_Callees = Callable[[_World, str, Jump], tuple[tuple[str, bool], ...]]


def link(
    tables: Mapping[str, ProgramTables],
    areas: CalleeAreas,
    transactions: Mapping[str, str],
    outside: OutsideJumps,
) -> Linked:
    return _rounds(_World(tables, frozenset(), outside, areas, transactions), 1)


def _rounds(world: _World, round_: int) -> Linked:
    found = frozenset(_edges(world))
    if found <= world.edges:
        return _linked(world, round_)
    return _rounds(replace(world, edges=world.edges | found), round_ + 1)


def _names(values: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted({v.rstrip() for v in values if is_program_name(v.rstrip())}))


def _fact_held(world: _World, program: str, node: str, fact: Fact) -> Held:
    if not fact.extent:
        return Held(values=frozenset(fact.values), reasons=frozenset(fact.reasons))
    return _held(world, program, node, byte_range(fact.extent, program), frozenset())


def _shifted(at: ByteRange, src: ByteRange, dst: ByteRange, program: str) -> ByteRange:
    start = max(at.start, src.start)
    end = min(at.end, src.end)
    return replace(
        dst,
        program=program,
        start=dst.start + start - src.start,
        end=dst.start + end - src.start,
    )


def _held(
    world: _World, program: str, node: str, at: ByteRange, visiting: _Visiting
) -> Held:
    if program not in world.tables:
        return _OUTSIDE
    visit = (program, node, at.region, at.start, at.end)
    if visit in visiting:
        return Held()
    found = resolve(world.tables[program], node, at)
    inner = visiting | {visit}
    return reduce(
        held_join,
        (_FOLLOW[stop.kind](world, program, stop, inner) for stop in found.stops),
        Held(values=found.values),
    )


def _unknown(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    return Held(reasons=frozenset(stop.reasons))


def _outside_callers(world: _World, program: str) -> Held:
    callers = world.outside.known_into.get(program, ())
    if not callers:
        return Held()
    return replace(_OUTSIDE, outside=frozenset(callers))


def _entering(edge: Edge, program: str, stop: Stop) -> bool:
    return (
        edge.callee == program
        and edge.kind in _ENTERING
        and edge.param == stop.param
        and edge.callee_window.covers(stop.at)
    )


def _received(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    into = tuple(e for e in world.edges if _entering(e, program, stop))
    from_callers = reduce(
        held_join,
        (
            _held(
                world,
                e.caller,
                e.node,
                _shifted(stop.at, e.callee_window, e.caller_window, e.caller),
                visiting,
            )
            for e in into
        ),
        Held(),
    )
    gaps = (
        Held() if into else Held(reasons=frozenset({UnresolvedReason.INBOUND_LINKAGE}))
    )
    return held_join(held_join(from_callers, gaps), _outside_callers(world, program))


def _returned(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    out = tuple(
        e
        for e in world.edges
        if e.caller == program and e.node == stop.node and e.param == stop.param
    )
    if not out:
        return Held(reasons=frozenset({UnresolvedReason.FROM_CALLEE}))
    return reduce(held_join, (_left_by(world, e, stop, visiting) for e in out), Held())


def _left_by(world: _World, edge: Edge, stop: Stop, visiting: _Visiting) -> Held:
    if edge.callee not in world.tables:
        return _OUTSIDE
    at = _shifted(stop.at, edge.caller_window, edge.callee_window, edge.callee)
    return reduce(
        held_join,
        (
            _held(world, edge.callee, exit_.node, at, visiting)
            for exit_ in world.tables[edge.callee].jumps.values()
            if exit_.kind is JumpKind.EXIT
        ),
        Held(),
    )


def _retrieved(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    starts = tuple(
        e
        for e in world.edges
        if e.kind is JumpKind.START
        and e.callee == program
        and e.callee_node == stop.node
    )
    if not starts:
        return Held(reasons=frozenset({UnresolvedReason.NOT_A_LITERAL}))
    return reduce(
        held_join,
        (
            _held(
                world,
                e.caller,
                e.node,
                _shifted(stop.at, e.callee_window, e.caller_window, e.caller),
                visiting,
            )
            for e in starts
        ),
        Held(),
    )


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
    found = _names(_fact_held(world, program, jump.node, jump.target).values)
    return tuple((name, name not in own) for name in found)


def _transaction_callees(
    world: _World, program: str, jump: Jump
) -> tuple[tuple[str, bool], ...]:
    own = frozenset(_names(frozenset(jump.transid.values)))
    found = _names(_fact_held(world, program, jump.node, jump.transid).values)
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
    theirs = world.areas.area(callee, kind, area.param)
    if not theirs.known:
        return ()
    return (
        Edge(
            program,
            jump.node,
            jump.kind,
            callee,
            area.param,
            *_lined_up(byte_range(area.extent, program), theirs),
            discovered=discovered,
        ),
    )


def _sorted_reasons(
    reasons: frozenset[UnresolvedReason],
) -> tuple[UnresolvedReason, ...]:
    return tuple(r for _, r in sorted((r.value, r) for r in reasons))


def _target(world: _World, program: str, node: str) -> LinkedTarget:
    tables = world.tables[program]
    site = tables.sites[node]
    held = _fact_held(world, program, node, tables.jumps[node].target)
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
