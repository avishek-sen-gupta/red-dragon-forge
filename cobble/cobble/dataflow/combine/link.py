"""Link programs: values cross programs over a call graph grown from those values, in rounds."""

import logging
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import partial, reduce
from itertools import accumulate, count, islice
from types import MappingProxyType

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.closures import Closures
from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.edge_index import EdgeIndex, edge_index
from cobble.dataflow.combine.held import Held, held_join
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolve import Resolve, resolve
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.targets import ResolvedTarget
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind

logger = logging.getLogger(__name__)

_ANSWER_HEARTBEAT = 5.0

_NAMED = frozenset({JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL})
_OUTSIDE = Held(reasons=frozenset({UnresolvedReason.OUTSIDE_ANALYSED_SET}))
_HOP_LIMIT = Held(reasons=frozenset({UnresolvedReason.HOP_LIMIT}))
_READBACK_SKIPPED = Held(reasons=frozenset({UnresolvedReason.READBACK_SKIPPED}))
_INBOUND = Held(reasons=frozenset({UnresolvedReason.INBOUND_LINKAGE}))
_FROM_CALLEE = Held(reasons=frozenset({UnresolvedReason.FROM_CALLEE}))
_NOT_A_LITERAL = Held(reasons=frozenset({UnresolvedReason.NOT_A_LITERAL}))
_Landing = tuple[str, str, ByteRange]
_Crossing = tuple[Held, tuple[_Landing, ...]]
_Vertex = tuple[str, str, ByteRange, int]
_Expansion = tuple[Held, tuple[_Vertex, ...]]
UNLIMITED_HOPS = sys.maxsize
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
    index: EdgeIndex
    max_hops: int
    readbacks: bool
    answers: Mapping[_Start, Held] = MappingProxyType({})


_Follow = Callable[[_World, str, Stop], _Crossing]
_Callees = Callable[[_World, str, Jump], tuple[tuple[str, bool], ...]]


def link(
    tables: Mapping[str, ProgramTables],
    areas: CalleeAreas,
    transactions: Mapping[str, str],
    outside: OutsideJumps,
    resolver: Resolve = resolve,
    max_hops: int = UNLIMITED_HOPS,
    readbacks: bool = True,
) -> Linked:
    world = _World(
        tables,
        frozenset(),
        outside,
        areas,
        transactions,
        resolver,
        edge_index(frozenset()),
        max_hops,
        readbacks,
    )
    return _rounds(_answered_in(world, 1))


_Round = tuple[_World, bool, int]


def _rounds(world: _World) -> Linked:
    """Rounds until one finds no edge the world does not already hold. Iterated,
    not recursed: a stack frame per round is a limit the corpus can reach."""
    runs = accumulate(count(1), _round, initial=(world, False, 0))
    settled, _, number = next(run for run in runs if run[1])
    return _linked(settled, number)


def _round(run: _Round, number: int) -> _Round:
    world = run[0]
    found = frozenset(_edges(world))
    logger.info(
        "combine:   round %d, %d edges total, %d new, %d programs",
        number,
        len(found),
        len(found - world.edges),
        len(world.tables),
    )
    if found <= world.edges:
        return world, True, number
    return (
        _answered_in(_with_edges(world, world.edges | found), number + 1),
        False,
        number,
    )


def position(
    round_: int, jump: int, jumps: int, index: int, programs: int, program: str
) -> str:
    """Where an answer sits in its round: the jump among every jump the round
    answers, so the fraction left is always on screen."""
    return (
        f"round {round_}: jump {jump}/{jumps} ({100 * jump // max(jumps, 1)}%),"
        f" program {index}/{programs} {program}"
    )


_Place = tuple[int, int, int, int, int]


def _program_answers(
    world: _World,
    program: str,
    tables: ProgramTables,
    place: _Place,
    closures: Closures[_Vertex, Held],
) -> tuple[tuple[_Start, Held], ...]:
    """``place`` is the round, the jumps answered before this program, every jump
    in the round, this program's number and every program in the round."""
    round_, before, jumps, index, programs = place
    return tuple(
        (
            (program, node, fact),
            _fact_held(
                world,
                program,
                node,
                fact,
                position(round_, before + number, jumps, index, programs, program),
                closures,
            ),
        )
        for number, (node, fact) in enumerate(_questions(tables), 1)
    )


def _questions(tables: ProgramTables) -> tuple[tuple[str, Fact], ...]:
    """Every operand this program's round must answer: each jump's target and
    transaction id, then each file site's operand."""
    return (
        *(
            (jump.node, fact)
            for jump in tables.jumps.values()
            for fact in (jump.target, jump.transid)
        ),
        *(
            (node, site.operand)
            for node, site in tables.sites.items()
            if site.kind is TargetKind.FILE
        ),
    )


def _collect_answers(
    world: _World,
    items: tuple[tuple[str, ProgramTables], ...],
    started: float,
    round_: int,
    closures: Closures[_Vertex, Held],
) -> tuple[tuple[_Start, Held], ...]:
    """Every program's answers, with a heartbeat at most every five seconds naming
    the position in the round. Iterated, not recursed: a corpus has thousands of
    programs, and a stack frame each is past the interpreter's limit."""
    befores = tuple(accumulate((len(tables.jumps) for _, tables in items), initial=0))
    jumps = befores[-1]
    places = tuple(
        (round_, befores[index - 1], jumps, index, len(items))
        for index in range(1, len(items) + 1)
    )
    stamps = accumulate(
        zip(items, places, strict=True),
        lambda last, pair: _heartbeat(pair, started, last),
        initial=started,
    )
    return tuple(
        answer
        for ((program, tables), place), _ in zip(
            zip(items, places, strict=True), islice(stamps, 1, None), strict=True
        )
        for answer in _program_answers(world, program, tables, place, closures)
    )


def _heartbeat(
    pair: tuple[tuple[str, ProgramTables], _Place], started: float, last: float
) -> float:
    (program, _), (round_, before, jumps, index, programs) = pair
    now = time.monotonic()
    if now - last < _ANSWER_HEARTBEAT:
        return last
    logger.info(
        "combine:   %s (%.1fs)",
        position(round_, before + 1, jumps, index, programs, program),
        now - started,
    )
    return now


def _answered_in(world: _World, round_: int) -> _World:
    total_programs = len(world.tables)
    total_jumps = sum(len(t.jumps) for t in world.tables.values())
    logger.info(
        "combine:   round %d: answering %d programs (%d jumps, %d edges)...",
        round_,
        total_programs,
        total_jumps,
        len(world.edges),
    )
    started = time.monotonic()
    closures = Closures(partial(_expanded, world), held_join, Held())
    pairs = _collect_answers(
        world, tuple(world.tables.items()), started, round_, closures
    )
    logger.info(
        "combine:   round %d: answered %d programs, %d jumps in %.1fs; %d vertices"
        " answered once each",
        round_,
        total_programs,
        total_jumps,
        time.monotonic() - started,
        closures.answered,
    )
    return replace(world, answers=MappingProxyType(dict(pairs)))


def _answer(world: _World, program: str, node: str, fact: Fact) -> Held:
    return world.answers[(program, node, fact)]


def _names(values: frozenset[str], kind: TargetKind) -> tuple[str, ...]:
    return tuple(sorted({v.rstrip() for v in values if kind.can_name(v.rstrip())}))


def _fact_held(
    world: _World,
    program: str,
    node: str,
    fact: Fact,
    label: str,
    closures: Closures[_Vertex, Held],
) -> Held:
    if not fact.extent:
        return Held(values=frozenset(fact.values), reasons=frozenset(fact.reasons))
    at = byte_range(fact.extent, program).bytes_only()
    return _held((program, node, at, 0), label, closures)


def _shifted(at: ByteRange, src: ByteRange, dst: ByteRange, program: str) -> ByteRange:
    start = max(at.start, src.start)
    end = min(at.end, src.end)
    return replace(
        dst,
        program=program,
        start=dst.start + start - src.start,
        end=dst.start + end - src.start,
    )


def _held(start: _Vertex, label: str, closures: Closures[_Vertex, Held]) -> Held:
    """What a walk from ``start`` would find -- everything reachable joined -- and
    whether it would reach some vertex twice, both from the round's memo."""
    return held_join(closures.of(start, label), Held(cycled=closures.revisits(start)))


def _joined(left: _Crossing, right: _Crossing) -> _Crossing:
    return held_join(left[0], right[0]), left[1] + right[1]


def _ending(held: Held) -> _Crossing:
    return held, ()


def _expanded(world: _World, vertex: _Vertex) -> _Expansion:
    program, node, at, hops = vertex
    found = world.resolver(world.tables[program], node, at)
    held, crossed = reduce(
        _joined,
        (_FOLLOW[stop.kind](world, program, stop) for stop in found.stops),
        _ending(Held(values=found.values)),
    )
    if crossed and hops >= world.max_hops:
        return held_join(held, _HOP_LIMIT), ()
    counted = hops + 1 if world.max_hops < UNLIMITED_HOPS else hops
    return held, tuple((p, n, a.bytes_only(), counted) for p, n, a in crossed)


def _unknown(world: _World, program: str, stop: Stop) -> _Crossing:
    return _ending(Held(reasons=frozenset(stop.reasons)))


def _outside_callers(world: _World, program: str) -> Held:
    callers = world.outside.known_into.get(program, ())
    if not callers:
        return Held()
    return replace(_OUTSIDE, outside=frozenset(callers))


def _from_caller(edge: Edge, stop: Stop) -> _Crossing:
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


def _with_edges(world: _World, edges: frozenset[Edge]) -> _World:
    return replace(world, edges=edges, index=edge_index(edges))


def _received(world: _World, program: str, stop: Stop) -> _Crossing:
    into = world.index.into.get((program, stop.param), ())
    from_callers = reduce(
        _joined, (_from_caller(e, stop) for e in into), _ending(Held())
    )
    gaps = Held() if into else _INBOUND
    return _joined(
        from_callers, _ending(held_join(gaps, _outside_callers(world, program)))
    )


def _read_back(world: _World, program: str, stop: Stop) -> _Crossing:
    if not world.readbacks:
        return _ending(_READBACK_SKIPPED)
    return _returned(world, program, stop)


def _returned(world: _World, program: str, stop: Stop) -> _Crossing:
    out = world.index.out.get((program, stop.node, stop.param), ())
    if not out:
        return _ending(_FROM_CALLEE)
    return reduce(_joined, (_left_by(world, e, stop) for e in out), _ending(Held()))


def _left_by(world: _World, edge: Edge, stop: Stop) -> _Crossing:
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


def _from_starter(edge: Edge, stop: Stop) -> _Crossing:
    if not edge.callee_window.covers(stop.at):
        return _ending(_NOT_A_LITERAL)
    at = _shifted(stop.at, edge.callee_window, edge.caller_window, edge.caller)
    return Held(), ((edge.caller, edge.node, at),)


def _retrieved(world: _World, program: str, stop: Stop) -> _Crossing:
    starts = world.index.started.get((program, stop.node), ())
    if not starts:
        return _ending(_NOT_A_LITERAL)
    return reduce(_joined, (_from_starter(e, stop) for e in starts), _ending(Held()))


_FOLLOW: Mapping[StopKind, _Follow] = {
    StopKind.UNKNOWN: _unknown,
    StopKind.RECEIVED: _received,
    StopKind.RETURNED: _read_back,
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
    own = frozenset(_names(frozenset(jump.target.values), TargetKind.PROGRAM))
    found = _names(
        _answer(world, program, jump.node, jump.target).values, TargetKind.PROGRAM
    )
    return tuple((name, name not in own) for name in found)


def _transaction_callees(
    world: _World, program: str, jump: Jump
) -> tuple[tuple[str, bool], ...]:
    own = frozenset(_names(frozenset(jump.transid.values), TargetKind.PROGRAM))
    found = _names(
        _answer(world, program, jump.node, jump.transid).values, TargetKind.PROGRAM
    )
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


def _operand(tables: ProgramTables, node: str) -> Fact:
    site = tables.sites[node]
    if site.kind is TargetKind.FILE:
        return site.operand
    return tables.jumps[node].target


def _answerable(tables: ProgramTables, node: str) -> bool:
    return node in tables.jumps or tables.sites[node].kind is TargetKind.FILE


def _target(world: _World, program: str, node: str) -> LinkedTarget:
    tables = world.tables[program]
    site = tables.sites[node]
    held = _answered(_answer(world, program, node, _operand(tables, node)))
    names = _names(held.values, site.kind)
    return LinkedTarget(
        ResolvedTarget(
            caller=program,
            node=node,
            kind=site.kind,
            transfer=site.transfer,
            expression=site.expression,
            candidates=names,
            reasons=_sorted_reasons(held.reasons),
            dropped=tuple(sorted({v.rstrip() for v in held.values} - set(names))),
            operand=site.operand,
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
            if _answerable(world.tables[program], node)
        ),
        edges=_sorted_edges(world.edges),
        report=RunReport(
            rounds=rounds,
            discovered=sum(1 for e in world.edges if e.discovered),
            unresolved_outside_jumps=world.outside.unresolved,
            without_results=world.outside.without_results,
        ),
    )
