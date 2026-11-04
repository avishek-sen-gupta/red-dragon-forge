"""One program's CFG as Horn rules: a relation per (context, node), a summary per PERFORM range."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby

import z3
from cobble.dataflow.srccfg.cfg import Edge, EdgeKind
from cobble.dataflow.srccfg.desugar import PERFORM_TRANSFER
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
from cobble.experimental.horn.effects import Byte, Effect, Kept, effect_of, everything
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.segment import Segment
from cobble.experimental.horn.storage import Storage, storage_of
from cobble.experimental.horn.terms import (
    bits,
    concat,
    conjunction,
    constant,
    equal,
    every,
    holds,
    negation,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HornSystem:
    rules: tuple[z3.BoolRef, ...]
    relations: tuple[z3.FuncDeclRef, ...]
    at: Mapping[Point, tuple[z3.FuncDeclRef, ...]]
    storage: Storage


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
        tuple(bits(f"e!{n}", s.length) for n, s in enumerate(storage.segments)),
        tuple(bits(f"s!{n}", s.length) for n, s in enumerate(storage.segments)),
        tuple(bits(f"t!{n}", s.length) for n, s in enumerate(storage.segments)),
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


def _sorts(segments: Sequence[Segment]) -> tuple[z3.BitVecSortRef, ...]:
    return tuple(z3.BitVecSort(8 * segment.length) for segment in segments)


def _relation(name: str, context: Context, storage: Storage) -> z3.FuncDeclRef:
    segments = storage.segments
    carried = (*segments, *segments) if context.is_range else segments
    return z3.Function(name, *_sorts(carried), z3.BoolSort())


def _runs(bytes_: Sequence[Byte]) -> tuple[tuple[Byte, int, int], ...]:
    positions = tuple(range(len(bytes_)))
    return tuple(
        (mark, group[0], group[-1] + 1)
        for mark, run in groupby(positions, key=lambda i: _run_key(bytes_[i]))
        for group in (tuple(run),)
    )


def _run_key(byte: Byte) -> Byte:
    return -1 if isinstance(byte, int) else byte


def _segment_step(
    tag: str,
    segment: Segment,
    bytes_: Sequence[Byte],
    values: tuple[z3.BitVecRef, z3.BitVecRef],
) -> Step:
    now, after = values
    if all(isinstance(byte, Kept) for byte in bytes_):
        return Step((equal(after, now),), ())
    pieces = tuple(_piece(tag, segment, bytes_, run, now) for run in _runs(bytes_))
    fresh = tuple(piece for piece, is_fresh in pieces if is_fresh)
    whole = concat(*(piece for piece, _ in pieces))
    return Step((equal(after, whole),), fresh)


def _piece(
    tag: str,
    segment: Segment,
    bytes_: Sequence[Byte],
    run: tuple[Byte, int, int],
    now: z3.BitVecRef,
) -> tuple[z3.BitVecRef, bool]:
    mark, start, end = run
    if isinstance(mark, Kept):
        return (segment.slice(segment.start + start, segment.start + end, now), False)
    if isinstance(mark, int):
        return (constant(bytes(_known(b) for b in bytes_[start:end])), False)
    return (bits(f"f!{tag}!{segment.start + start}", end - start), True)


def _known(byte: Byte) -> int:
    if isinstance(byte, int):
        return byte
    raise TypeError(f"{byte} is not a known byte")


def _step(lowering: Lowering, tag: str, effect: Effect) -> Step:
    v = lowering.vars
    steps_ = tuple(
        _segment_step(f"{tag}!{n}", segment, bytes_, (now, after))
        for n, (segment, bytes_, now, after) in enumerate(
            zip(lowering.storage.segments, effect.bytes, v.now, v.after, strict=True)
        )
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
    if not atom.plain:
        return ()
    terms = comparison(
        atom.left, atom.op, atom.right, lowering.storage, lowering.vars.now
    )
    return terms if edge.kind is EdgeKind.TRUE else tuple(negation(t) for t in terms)


def _edge_rule(lowering: Lowering, context: Context, edge: Edge) -> z3.BoolRef:
    v = lowering.vars
    step = _step(lowering, _tag(edge), _edge_effect(lowering, edge))
    body = (
        lowering.at(context, edge.source, v.entry, v.now),
        *step.terms,
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
    )


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


def _lowering(program: Program) -> Lowering:
    cfg = program.cfg
    storage = storage_of(cfg, program.index)
    reach = {context: members(cfg, context) for context in contexts(cfg)}
    return Lowering(
        program,
        storage,
        reach,
        {
            (context, node): _relation(f"at[{index}]{node}", context, storage)
            for index, context in enumerate(reach)
            for node in reach[context]
        },
        {
            context: _relation(f"sum[{index}]", context, storage)
            for index, context in enumerate(reach)
            if context.is_range
        },
        {node.id: effect_of(program, storage, node.id) for node in cfg.nodes},
        states(storage),
    )


def _at(lowering: Lowering) -> Mapping[Point, tuple[z3.FuncDeclRef, ...]]:
    cfg = lowering.program.cfg
    return {
        Point(cfg.program, node.id): tuple(
            lowering.relations[(context, node.id)]
            for context in lowering.members
            if node.id in lowering.members[context]
        )
        for node in cfg.nodes
    }


def lower(program: Program) -> HornSystem:
    lowering = _lowering(program)
    rules = (
        _start(lowering),
        *(
            rule
            for context in lowering.members
            for part in (_edge_rules, _call_rules, _summary_rules)
            for rule in part(lowering, context)
        ),
    )
    relations = (*lowering.relations.values(), *lowering.summaries.values())
    logger.info(
        "%s: %d segments, %d tracked bytes, %d contexts, %d relations, %d rules",
        program.cfg.program,
        len(lowering.storage.segments),
        sum(segment.length for segment in lowering.storage.segments),
        len(lowering.members),
        len(relations),
        len(rules),
    )
    return HornSystem(rules, relations, _at(lowering), lowering.storage)
