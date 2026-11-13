"""One program's CFG as Horn rules: a relation per (context, node), a summary per PERFORM range."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import groupby

import z3
from cobble.dataflow.srccfg.cfg import Edge, EdgeKind, NodeKind
from cobble.dataflow.srccfg.desugar import DISPATCH_TRANSFER_CICS, PERFORM_TRANSFER
from cobble.experimental.horn.atoms import comparison
from cobble.experimental.horn.context import (
    Context,
    contexts,
    members,
    perform_edge,
    performed,
    steps,
    top,
)
from cobble.experimental.horn.effects import (
    Byte,
    Copied,
    Digit,
    Effect,
    Kept,
    Within,
    effect_of,
    everything,
)
from cobble.experimental.horn.every_test import EVERY_TEST
from cobble.experimental.horn.followed import raising, unfollowed
from cobble.experimental.horn.kept_tests import KeptTests
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.segment import Segment
from cobble.experimental.horn.storage import EIBCALEN, Storage, storage_of
from cobble.experimental.horn.terms import (
    RAN,
    above,
    bits,
    chosen,
    concat,
    conjunction,
    constant,
    equal,
    every,
    extract,
    holds,
    negation,
    nibble,
)
from cobble.experimental.horn.xctl import (
    pgmiderr_handlers,
    program_field,
)
from cobol_memory.region_id import RegionId

logger = logging.getLogger(__name__)

PAD = b" "
NOTHING_INSTALLED: frozenset[str] = frozenset()
UNSET = constant(b"\x00")
OUTCOMES: Mapping[EdgeKind, Outcome] = {
    EdgeKind.TRUE: Outcome.TRUE,
    EdgeKind.FALSE: Outcome.FALSE,
}


@dataclass(frozen=True)
class HornSystem:
    """``storages`` holds each program's, by name."""

    rules: tuple[z3.BoolRef, ...]
    relations: tuple[z3.FuncDeclRef, ...]
    at: Mapping[Point, tuple[z3.FuncDeclRef, ...]]
    storages: Mapping[str, Storage]


@dataclass(frozen=True)
class States:
    entry: tuple[z3.BitVecRef, ...]
    now: tuple[z3.BitVecRef, ...]
    after: tuple[z3.BitVecRef, ...]

    @property
    def variables(self) -> tuple[z3.BitVecRef, ...]:
        return (*self.entry, *self.now, *self.after)


def states(storage: Storage) -> States:
    return States(
        tuple(bits(f"e!{n}", width) for n, width in enumerate(storage.widths)),
        tuple(bits(f"s!{n}", width) for n, width in enumerate(storage.widths)),
        tuple(bits(f"t!{n}", width) for n, width in enumerate(storage.widths)),
    )


@dataclass(frozen=True)
class Lowering:
    program: Program
    storage: Storage
    members: Mapping[Context, frozenset[str]]
    relations: Mapping[tuple[Context, str], z3.FuncDeclRef]
    summaries: Mapping[Context, z3.FuncDeclRef]
    effects: Mapping[str, Effect]
    vars: States
    cut: frozenset[Edge]
    installed: frozenset[str] = NOTHING_INSTALLED

    def at(
        self,
        context: Context,
        node: str,
        entry: Sequence[z3.BitVecRef],
        now: Sequence[z3.BitVecRef],
    ) -> z3.BoolRef:
        relation = self.relations[(context, node)]
        return holds(relation, *(entry if context.is_range else ()), *now)


@dataclass(frozen=True)
class Step:
    """One rule's body terms for an effect, and the fresh bytes it introduces."""

    terms: tuple[z3.BoolRef, ...]
    fresh: tuple[z3.BitVecRef, ...]


def _rule(
    lowering: Lowering,
    body: Sequence[z3.BoolRef],
    head: z3.BoolRef,
    fresh: Sequence[z3.BitVecRef] = (),
) -> z3.BoolRef:
    variables = (*lowering.vars.variables, *fresh)
    return every(variables, z3.Implies(conjunction(*body), head))


def sorts(widths: Sequence[int]) -> tuple[z3.BitVecSortRef, ...]:
    return tuple(z3.BitVecSort(8 * width) for width in widths)


def _relation(name: str, context: Context, storage: Storage) -> z3.FuncDeclRef:
    widths = storage.widths
    carried = (*widths, *widths) if context.is_range else widths
    return z3.Function(name, *sorts(carried), z3.BoolSort())


def _runs(bytes_: Sequence[Byte]) -> tuple[tuple[Byte, int, int], ...]:
    positions = tuple(range(len(bytes_)))
    return tuple(
        (bytes_[group[0]], group[0], group[-1] + 1)
        for _, run in groupby(positions, key=lambda i: _run_key(bytes_[i], i))
        for group in (tuple(run),)
    )


def _run_key(byte: Byte, i: int) -> Byte:
    """Bytes that one piece covers share a key: known bytes, a write's fresh
    bytes, or copied bytes or digits whose sources are consecutive."""
    if isinstance(byte, int):
        return -1
    if isinstance(byte, Copied | Digit):
        return replace(byte, offset=byte.offset - i)
    return byte


def _segment_step(
    lowering: Lowering,
    tag: str,
    n: int,
    bytes_: Sequence[Byte],
) -> Step:
    now, after = lowering.vars.now[n], lowering.vars.after[n]
    if all(isinstance(byte, Kept) for byte in bytes_):
        return Step((equal(after, now),), ())
    segment = lowering.storage.segments[n]
    pieces = tuple(
        _piece(lowering, tag, segment, bytes_, run, now) for run in _runs(bytes_)
    )
    fresh = tuple(variable for _, made in pieces for variable in made)
    whole = concat(*(piece for piece, _ in pieces))
    return Step((equal(after, whole),), fresh)


def _piece(
    lowering: Lowering,
    tag: str,
    segment: Segment,
    bytes_: Sequence[Byte],
    run: tuple[Byte, int, int],
    now: z3.BitVecRef,
) -> tuple[z3.BitVecRef, tuple[z3.BitVecRef, ...]]:
    """One run's bytes, and the fresh variables they introduce."""
    mark, start, end = run
    if isinstance(mark, Kept | Copied | Digit | Within):
        return _held(lowering, tag, segment, mark, (start, end), now)
    if isinstance(mark, int):
        return (constant(bytes(_known(b) for b in bytes_[start:end])), ())
    fresh = bits(f"f!{tag}!{segment.start + start}", end - start)
    return (fresh, (fresh,))


def _held(
    lowering: Lowering,
    tag: str,
    segment: Segment,
    mark: Kept | Copied | Digit | Within,
    run: tuple[int, int],
    now: z3.BitVecRef,
) -> tuple[z3.BitVecRef, tuple[z3.BitVecRef, ...]]:
    start, end = run
    if isinstance(mark, Within):
        return (_within(lowering, mark), ())
    if isinstance(mark, Digit):
        return _digits(lowering, mark, end - start, f"{tag}!{segment.start + start}")
    return (_found(lowering, segment, mark, run, now), ())


def _found(
    lowering: Lowering,
    segment: Segment,
    mark: Kept | Copied,
    run: tuple[int, int],
    now: z3.BitVecRef,
) -> z3.BitVecRef:
    """Bytes the state already holds: the segment's own, or a copy's source."""
    start, end = run
    if isinstance(mark, Copied):
        return _copied(lowering, mark.region, mark.offset, end - start)
    return segment.slice(segment.start + start, segment.start + end, now)


def _copied(
    lowering: Lowering, region: RegionId, offset: int, length: int
) -> z3.BitVecRef:
    n = lowering.storage.placed(region, offset)
    source = lowering.storage.segments[n]
    return source.slice(offset, offset + length, lowering.vars.now[n])


def _within(lowering: Lowering, byte: Within) -> z3.BitVecRef:
    calen = lowering.storage.calen(lowering.vars.now)
    source = _copied(lowering, byte.region, byte.offset, 1)
    return chosen(above(calen, byte.position), source, constant(PAD))


def _digits(
    lowering: Lowering, first: Digit, length: int, tag: str
) -> tuple[z3.BitVecRef, tuple[z3.BitVecRef, ...]]:
    """Each source byte's digit half under a fresh zone."""
    source = _copied(lowering, first.region, first.offset, length)
    zones = tuple(nibble(f"z!{tag}!{k}") for k in range(length))
    low = tuple(8 * (length - k - 1) for k in range(length))
    term = concat(
        *(concat(zones[k], extract(low[k] + 3, low[k], source)) for k in range(length))
    )
    return (term, zones)


def _known(byte: Byte) -> int:
    if isinstance(byte, int):
        return byte
    raise TypeError(f"{byte} is not a known byte")


def _step(lowering: Lowering, tag: str, effect: Effect) -> Step:
    steps_ = tuple(
        _segment_step(lowering, f"{tag}!{n}", n, bytes_)
        for n, bytes_ in enumerate(effect.bytes)
    )
    return Step(
        tuple(t for s in steps_ for t in s.terms),
        tuple(f for s in steps_ for f in s.fresh),
    )


def _edge_effect(lowering: Lowering, edge: Edge) -> Effect:
    """The FLOW edge the CFG keeps past a PERFORM it could not resolve, or whose
    range never returns, stands for whatever the range might have done."""
    node = lowering.program.cfg.node(edge.source)
    if edge.kind is EdgeKind.FLOW and node.transfer == PERFORM_TRANSFER:
        return everything(lowering.storage)
    return lowering.effects[edge.source]


def _guard(lowering: Lowering, edge: Edge) -> tuple[z3.BoolRef, ...]:
    if edge.kind not in (EdgeKind.TRUE, EdgeKind.FALSE):
        return ()
    atom = lowering.program.cfg.node(edge.source).atom
    if not atom.plain or not lowering.storage.kept.keeps(atom):
        return ()
    branches = comparison(
        atom.left, atom.op, atom.right, lowering.storage, lowering.vars.now
    )
    return branches.true if edge.kind is EdgeKind.TRUE else branches.false


def _extras(lowering: Lowering, edge: Edge) -> tuple[z3.BoolRef, ...]:
    """EIBCALEN as the task found it, unless the node writes it; each mark as it
    was, or 1 leaving its own point; each outcome mark as it was, or the outcome
    of the edge leaving its test; each entry mark as it was."""
    storage, v = lowering.storage, lowering.vars
    base = len(storage.segments)
    node = lowering.program.cfg.node(edge.source)
    calen = (
        (equal(v.after[base], v.now[base]),)
        if storage.eib and EIBCALEN not in node.writes
        else ()
    )
    here = Point(lowering.program.cfg.program, edge.source)
    first = base + int(storage.eib)
    marks = tuple(
        equal(v.after[first + k], RAN if mark == here else v.now[first + k])
        for k, mark in enumerate(storage.marks)
    )
    return (*calen, *marks, *_outcomes(lowering, edge), *_entries_kept(lowering))


def _outcomes(lowering: Lowering, edge: Edge) -> tuple[z3.BoolRef, ...]:
    storage, v = lowering.storage, lowering.vars
    taken = OUTCOMES.get(edge.kind, Outcome.UNRUN)
    return tuple(
        equal(
            storage.outcome(test, v.after),
            (
                outcome_byte(taken)
                if test == edge.source and taken is not Outcome.UNRUN
                else storage.outcome(test, v.now)
            ),
        )
        for test in storage.outcomes
    )


def _entries_kept(lowering: Lowering) -> tuple[z3.BoolRef, ...]:
    storage, v = lowering.storage, lowering.vars
    return tuple(
        equal(storage.entry(e.range, v.after), storage.entry(e.range, v.now))
        for e in storage.entries
    )


def outcome_byte(outcome: Outcome) -> z3.BitVecRef:
    return constant(bytes((outcome.value,)))


def _edge_rule(lowering: Lowering, context: Context, edge: Edge) -> z3.BoolRef:
    v = lowering.vars
    step = _step(lowering, _tag(edge), _edge_effect(lowering, edge))
    body = (
        lowering.at(context, edge.source, v.entry, v.now),
        *step.terms,
        *_extras(lowering, edge),
        *_guard(lowering, edge),
        *_installed(lowering, edge),
    )
    head = lowering.at(context, edge.target, v.entry, v.after)
    return _rule(lowering, body, head, step.fresh)


def _installed(lowering: Lowering, edge: Edge) -> tuple[z3.BoolRef, ...]:
    """The dispatch into a handler armed for PGMIDERR alone, from an XCTL, only
    while it names a program not installed. The dispatch from a command that
    cannot raise PGMIDERR is not followed at all."""
    if not _into_pgmiderr(lowering, edge):
        return ()
    commands = raising(lowering.program, edge)
    if len(commands) != 1:
        return ()
    return _not_naming(lowering, program_field(lowering.program, commands[0]))


def _into_pgmiderr(lowering: Lowering, edge: Edge) -> bool:
    cfg = lowering.program.cfg
    return (
        edge.kind is EdgeKind.GOTO
        and cfg.node(edge.source).transfer == DISPATCH_TRANSFER_CICS
        and cfg.node(edge.target).paragraph in pgmiderr_handlers(lowering.program)
    )


def _not_naming(lowering: Lowering, field: str) -> tuple[z3.BoolRef, ...]:
    storage = lowering.storage
    extents = storage.tracked(field) if field else ()
    if not extents:
        return ()
    held = storage.value(extents[0], lowering.vars.now)
    return tuple(
        negation(equal(held, constant(padded)))
        for name in sorted(lowering.installed)
        for padded in (name.encode("ascii").ljust(extents[0].length),)
        if len(padded) == extents[0].length
    )


def _tag(edge: Edge) -> str:
    return f"{edge.source}>{edge.target}"


def _edge_rules(lowering: Lowering, context: Context) -> tuple[z3.BoolRef, ...]:
    return tuple(
        _edge_rule(lowering, context, edge)
        for node in sorted(lowering.members[context])
        for edge in steps(lowering.program.cfg, context, node)
        if edge not in lowering.cut
    )


def _call(lowering: Lowering, context: Context, edge: Edge) -> tuple[z3.BoolRef, ...]:
    v = lowering.vars
    callee = performed(lowering.program.cfg, edge)
    caller = lowering.at(context, edge.source, v.entry, v.now)
    entered = _entered(lowering, callee, edge.source)
    enter = _rule(
        lowering, (caller,), lowering.at(callee, callee.entry, entered, entered)
    )
    return (enter, *_resume(lowering, context, edge, callee))


def _entered(
    lowering: Lowering, callee: Context, call: str
) -> tuple[z3.BitVecRef, ...]:
    """The caller's state with the callee's entry mark, if it has one, naming
    ``call``."""
    storage, now = lowering.storage, lowering.vars.now
    marked = tuple(e for e in storage.entries if e.range == callee)
    if not marked:
        return now
    at = len(now) - len(storage.entries) + storage.entered(callee)
    value = constant(bytes((marked[0].value(call),)))
    return (*now[:at], value, *now[at + 1 :])


def _resume(
    lowering: Lowering, context: Context, edge: Edge, callee: Context
) -> tuple[z3.BoolRef, ...]:
    v = lowering.vars
    resume = lowering.program.cfg.node(edge.source).resume
    if resume not in lowering.members[context]:
        return ()
    entered = _entered(lowering, callee, edge.source)
    body = (
        lowering.at(context, edge.source, v.entry, v.now),
        holds(lowering.summaries[callee], *entered, *v.after),
    )
    return (_rule(lowering, body, lowering.at(context, resume, v.entry, v.after)),)


def _call_rules(lowering: Lowering, context: Context) -> tuple[z3.BoolRef, ...]:
    return tuple(
        rule
        for node in sorted(lowering.members[context])
        for edge in perform_edge(lowering.program.cfg, node)
        for rule in _call(lowering, context, edge)
    )


def _summary_rules(lowering: Lowering, context: Context) -> tuple[z3.BoolRef, ...]:
    if not context.is_range or context.end not in lowering.members[context]:
        return ()
    v = lowering.vars
    body = (lowering.at(context, context.end, v.now, v.after),)
    summary = holds(lowering.summaries[context], *v.now, *v.after)
    return (_rule(lowering, body, summary),)


def _start(lowering: Lowering) -> z3.BoolRef:
    """Any state, but no test has run and no range has been entered."""
    v = lowering.vars
    cfg = lowering.program.cfg
    storage = lowering.storage
    unset = (
        *(storage.outcome(test, v.now) for test in storage.outcomes),
        *(storage.entry(e.range, v.now) for e in storage.entries),
    )
    body = tuple(equal(byte, UNSET) for byte in unset)
    return _rule(lowering, body, lowering.at(top(cfg), cfg.entry, v.entry, v.now))


def lowering_of(
    program: Program,
    storage: Storage,
    installed: frozenset[str] = NOTHING_INSTALLED,
) -> Lowering:
    cfg = program.cfg
    _check_marks(program, storage)
    reach = {context: members(cfg, context) for context in contexts(cfg)}
    return Lowering(
        program,
        storage,
        reach,
        {
            (context, node): _relation(
                f"{cfg.program}:at[{index}]{node}", context, storage
            )
            for index, context in enumerate(reach)
            for node in reach[context]
        },
        {
            context: _relation(f"{cfg.program}:sum[{index}]", context, storage)
            for index, context in enumerate(reach)
            if context.is_range
        },
        {node.id: effect_of(program, storage, node.id) for node in cfg.nodes},
        states(storage),
        unfollowed(program),
        installed,
    )


def _check_marks(program: Program, storage: Storage) -> None:
    _check_points(program, storage)
    _check_outcomes(program, storage)
    _check_entries(program, storage)


def _check_points(program: Program, storage: Storage) -> None:
    """A mark is set leaving its point, so a point left only by a PERFORM, or not
    left at all, would never be marked."""
    cfg = program.cfg
    unmarkable = tuple(
        mark
        for mark in storage.marks
        if mark.program == cfg.program
        and (mark.node not in cfg.node_ids or not steps(cfg, top(cfg), mark.node))
    )
    if unmarkable:
        raise ValueError(f"{unmarkable[0]} cannot be marked")


def _check_outcomes(program: Program, storage: Storage) -> None:
    cfg = program.cfg
    tests = frozenset(n.id for n in cfg.nodes if n.kind is NodeKind.TEST)
    untested = tuple(test for test in storage.outcomes if test not in tests)
    if untested:
        raise ValueError(f"{untested[0]} is not a test of {cfg.program}")


def _check_entries(program: Program, storage: Storage) -> None:
    cfg = program.cfg
    ranges = frozenset(contexts(cfg))
    unranged = tuple(e.range for e in storage.entries if e.range not in ranges)
    if unranged:
        raise ValueError(f"{unranged[0]} is not a context of {cfg.program}")


def relations_of(lowering: Lowering) -> tuple[z3.FuncDeclRef, ...]:
    return (*lowering.relations.values(), *lowering.summaries.values())


def body_rules(lowering: Lowering) -> tuple[z3.BoolRef, ...]:
    """Every rule but the one that starts the program."""
    rules = tuple(
        rule
        for context in lowering.members
        for part in (_edge_rules, _call_rules, _summary_rules)
        for rule in part(lowering, context)
    )
    logger.info(
        "%s: %d segments, %d tracked bytes, %d contexts, %d relations, %d rules",
        lowering.program.cfg.program,
        len(lowering.storage.segments),
        sum(segment.length for segment in lowering.storage.segments),
        len(lowering.members),
        len(relations_of(lowering)),
        len(rules),
    )
    return rules


def points_of(lowering: Lowering) -> Mapping[Point, tuple[z3.FuncDeclRef, ...]]:
    cfg = lowering.program.cfg
    return {
        Point(cfg.program, node.id): tuple(
            lowering.relations[(context, node.id)]
            for context in lowering.members
            if node.id in lowering.members[context]
        )
        for node in cfg.nodes
    }


def lower(
    program: Program,
    watched: Sequence[str] = (),
    marks: Sequence[Point] = (),
    kept: KeptTests = EVERY_TEST,
    outcomes: Sequence[str] = (),
    entries: Sequence[Context] = (),
) -> HornSystem:
    """One task of ``program``, entered in any state. ``watched`` names the
    fields a question will ask about, beside the ones the program's own tests
    read; ``marks`` the points a question will ask whether the task has passed;
    ``kept`` the tests to keep; ``outcomes`` the tests a question will ask the
    last outcome of; ``entries`` the ranges it will ask the last call site of."""
    storage = storage_of(program, watched, marks, frozenset(), kept, outcomes, entries)
    lowering = lowering_of(program, storage)
    return HornSystem(
        (_start(lowering), *body_rules(lowering)),
        relations_of(lowering),
        points_of(lowering),
        {program.cfg.program: lowering.storage},
    )
