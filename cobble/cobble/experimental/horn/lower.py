"""One program's CFG as Horn rules: a relation per (context, node), a summary per PERFORM range."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import groupby

import z3
from cobble.dataflow.srccfg.cfg import Edge, EdgeKind
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
from cobble.experimental.horn.kept_tests import KeptTests
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
    nibble,
)
from cobol_asg.cobol_statements import (
    AlterStatement,
    ExitProgramStatement,
    GobackStatement,
    StopRunStatement,
)
from cobol_memory.region_id import RegionId

logger = logging.getLogger(__name__)

PAD = b" "
TERMINATORS = (StopRunStatement, GobackStatement, ExitProgramStatement)


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
    was, or 1 leaving its own point."""
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
    return (*calen, *marks)


def _edge_rule(lowering: Lowering, context: Context, edge: Edge) -> z3.BoolRef:
    v = lowering.vars
    step = _step(lowering, _tag(edge), _edge_effect(lowering, edge))
    body = (
        lowering.at(context, edge.source, v.entry, v.now),
        *step.terms,
        *_extras(lowering, edge),
        *_guard(lowering, edge),
    )
    head = lowering.at(context, edge.target, v.entry, v.after)
    return _rule(lowering, body, head, step.fresh)


def _tag(edge: Edge) -> str:
    return f"{edge.source}>{edge.target}"


def _edge_rules(lowering: Lowering, context: Context) -> tuple[z3.BoolRef, ...]:
    return tuple(
        _edge_rule(lowering, context, edge)
        for node in sorted(lowering.members[context])
        for edge in steps(lowering.program.cfg, context, node)
        if not _never_back(lowering, edge)
    )


def _never_back(lowering: Lowering, edge: Edge) -> bool:
    """The FLOW edge the CFG keeps past a PERFORM whose range end nothing reaches,
    when every way out of the range ends the task and no ALTER can redirect a GO
    TO: the PERFORM cannot come back, so the edge is not a path."""
    cfg = lowering.program.cfg
    if (
        edge.kind is not EdgeKind.FLOW
        or cfg.node(edge.source).transfer != PERFORM_TRANSFER
    ):
        return False
    calls = perform_edge(cfg, edge.source)
    return (
        bool(calls)
        and not _altered(lowering)
        and all(
            _ends_task(lowering, node)
            for call in calls
            for node in lowering.members[performed(cfg, call)]
            if not cfg.successors(node)
        )
    )


def _altered(lowering: Lowering) -> bool:
    return any(
        isinstance(statement, AlterStatement)
        for statement in lowering.program.statements.values()
    )


def _ends_task(lowering: Lowering, node: str) -> bool:
    """STOP RUN, GOBACK, EXIT PROGRAM, or a CICS condition no handler takes."""
    if lowering.program.cfg.node(node).transfer == DISPATCH_TRANSFER_CICS:
        return True
    return isinstance(lowering.program.statements.get(node), TERMINATORS)


def _call(lowering: Lowering, context: Context, edge: Edge) -> tuple[z3.BoolRef, ...]:
    v = lowering.vars
    callee = performed(lowering.program.cfg, edge)
    caller = lowering.at(context, edge.source, v.entry, v.now)
    enter = _rule(lowering, (caller,), lowering.at(callee, callee.entry, v.now, v.now))
    return (enter, *_resume(lowering, context, edge, callee))


def _resume(
    lowering: Lowering, context: Context, edge: Edge, callee: Context
) -> tuple[z3.BoolRef, ...]:
    v = lowering.vars
    resume = lowering.program.cfg.node(edge.source).resume
    if resume not in lowering.members[context]:
        return ()
    body = (
        lowering.at(context, edge.source, v.entry, v.now),
        holds(lowering.summaries[callee], *v.now, *v.after),
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
    v = lowering.vars
    cfg = lowering.program.cfg
    return _rule(lowering, (), lowering.at(top(cfg), cfg.entry, v.entry, v.now))


def lowering_of(program: Program, storage: Storage) -> Lowering:
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
    )


def _check_marks(program: Program, storage: Storage) -> None:
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
) -> HornSystem:
    """One task of ``program``, entered in any state. ``watched`` names the
    fields a question will ask about, beside the ones the program's own tests
    read; ``marks`` the points a question will ask whether the task has passed;
    ``kept`` the tests to keep."""
    lowering = lowering_of(
        program, storage_of(program, watched, marks, frozenset(), kept)
    )
    return HornSystem(
        (_start(lowering), *body_rules(lowering)),
        relations_of(lowering),
        points_of(lowering),
        {program.cfg.program: lowering.storage},
    )
