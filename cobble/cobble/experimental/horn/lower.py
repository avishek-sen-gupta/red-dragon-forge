"""One program's CFG as Horn rules: a relation per (context, node), a summary per PERFORM range."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import z3
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind
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
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.terms import (
    conjunction,
    equal,
    every,
    holds,
    negation,
    string,
)
from cobble.experimental.horn.tracked import Tracked, declarations, tracked_fields

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HornSystem:
    rules: tuple[z3.BoolRef, ...]
    relations: tuple[z3.FuncDeclRef, ...]
    at: Mapping[Point, tuple[z3.FuncDeclRef, ...]]
    fields: tuple[Tracked, ...]


@dataclass(frozen=True)
class States:
    entry: tuple[z3.SeqRef, ...]
    now: tuple[z3.SeqRef, ...]
    after: tuple[z3.SeqRef, ...]

    @property
    def variables(self) -> tuple[z3.SeqRef, ...]:
        return (*self.entry, *self.now, *self.after)


def states(fields: Sequence[Tracked]) -> States:
    return States(
        tuple(string(f"e!{field.name}") for field in fields),
        tuple(string(f"s!{field.name}") for field in fields),
        tuple(string(f"t!{field.name}") for field in fields),
    )


@dataclass(frozen=True)
class Lowering:
    cfg: Cfg
    fields: tuple[Tracked, ...]
    written: Mapping[str, tuple[ByteRange, ...]]
    members: Mapping[Context, frozenset[str]]
    relations: Mapping[tuple[Context, str], z3.FuncDeclRef]
    summaries: Mapping[Context, z3.FuncDeclRef]
    vars: States

    def at(
        self,
        context: Context,
        node: str,
        entry: Sequence[z3.SeqRef],
        now: Sequence[z3.SeqRef],
    ) -> z3.BoolRef:
        relation = self.relations[(context, node)]
        return holds(relation, *(entry if context.is_range else ()), *now)

    def by_name(self, values: Sequence[z3.SeqRef]) -> Mapping[str, z3.SeqRef]:
        return {
            field.name: value for field, value in zip(self.fields, values, strict=True)
        }


def _rule(
    lowering: Lowering, body: Sequence[z3.BoolRef], head: z3.BoolRef
) -> z3.BoolRef:
    return every(lowering.vars.variables, z3.Implies(conjunction(*body), head))


def _sorts(count: int) -> tuple[z3.SeqSortRef, ...]:
    return tuple(z3.StringSort() for _ in range(count))


def _relation(name: str, context: Context, fields: int) -> z3.FuncDeclRef:
    width = 2 * fields if context.is_range else fields
    return z3.Function(name, *_sorts(width), z3.BoolSort())


def _written(program: Program) -> Mapping[str, tuple[ByteRange, ...]]:
    declared = declarations(program.extents)
    names = frozenset(entry.name for entry in declared)
    return {
        name: tuple(entry.extent for entry in declared if entry.name == name)
        for name in names
    }


def _length(value: z3.SeqRef, field: Tracked) -> z3.BoolRef:
    return equal(z3.Length(value), z3.IntVal(field.length))


def _freed(lowering: Lowering, node: str, field: Tracked) -> bool:
    return any(
        extent.overlaps(field.extent)
        for name in lowering.cfg.node(node).writes
        for extent in lowering.written.get(name, ())
    )


def _effect(lowering: Lowering, node: str) -> tuple[z3.BoolRef, ...]:
    return tuple(
        _length(after, field) if _freed(lowering, node, field) else equal(after, now)
        for field, now, after in zip(
            lowering.fields, lowering.vars.now, lowering.vars.after, strict=True
        )
    )


def _guard(lowering: Lowering, edge: Edge) -> tuple[z3.BoolRef, ...]:
    if edge.kind not in (EdgeKind.TRUE, EdgeKind.FALSE):
        return ()
    atom = lowering.cfg.node(edge.source).atom
    fields = {field.name: field for field in lowering.fields}
    terms = comparison(
        atom.left, atom.op, atom.right, lowering.by_name(lowering.vars.now), fields
    )
    return terms if edge.kind is EdgeKind.TRUE else tuple(negation(t) for t in terms)


def _edge_rule(lowering: Lowering, context: Context, edge: Edge) -> z3.BoolRef:
    v = lowering.vars
    body = (
        lowering.at(context, edge.source, v.entry, v.now),
        *_effect(lowering, edge.source),
        *_guard(lowering, edge),
    )
    return _rule(lowering, body, lowering.at(context, edge.target, v.entry, v.after))


def _edge_rules(lowering: Lowering, context: Context) -> tuple[z3.BoolRef, ...]:
    return tuple(
        _edge_rule(lowering, context, edge)
        for node in sorted(lowering.members[context])
        for edge in steps(lowering.cfg, context, node)
    )


def _call(lowering: Lowering, context: Context, edge: Edge) -> tuple[z3.BoolRef, ...]:
    v = lowering.vars
    callee = performed(lowering.cfg, edge)
    caller = lowering.at(context, edge.source, v.entry, v.now)
    enter = _rule(lowering, (caller,), lowering.at(callee, callee.entry, v.now, v.now))
    return (enter, *_resume(lowering, context, edge, callee))


def _resume(
    lowering: Lowering, context: Context, edge: Edge, callee: Context
) -> tuple[z3.BoolRef, ...]:
    v = lowering.vars
    resume = lowering.cfg.node(edge.source).resume
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
        for edge in perform_edge(lowering.cfg, node)
        for rule in _call(lowering, context, edge)
    )


def _summary_rules(lowering: Lowering, context: Context) -> tuple[z3.BoolRef, ...]:
    if not context.is_range or context.end not in lowering.members[context]:
        return ()
    v = lowering.vars
    body = (lowering.at(context, context.end, v.now, v.after),)
    return (
        _rule(lowering, body, holds(lowering.summaries[context], *v.now, *v.after)),
    )


def _start(lowering: Lowering) -> z3.BoolRef:
    v = lowering.vars
    body = tuple(
        _length(now, field) for field, now in zip(lowering.fields, v.now, strict=True)
    )
    head = lowering.at(top(lowering.cfg), lowering.cfg.entry, v.entry, v.now)
    return _rule(lowering, body, head)


def _lowering(program: Program) -> Lowering:
    cfg = program.cfg
    fields = tracked_fields(cfg, program.extents)
    reach = {context: members(cfg, context) for context in contexts(cfg)}
    return Lowering(
        cfg,
        fields,
        _written(program),
        reach,
        {
            (context, node): _relation(f"at[{index}]{node}", context, len(fields))
            for index, context in enumerate(reach)
            for node in reach[context]
        },
        {
            context: _relation(f"sum[{index}]", context, len(fields))
            for index, context in enumerate(reach)
            if context.is_range
        },
        states(fields),
    )


def _at(lowering: Lowering) -> Mapping[Point, tuple[z3.FuncDeclRef, ...]]:
    return {
        Point(lowering.cfg.program, node.id): tuple(
            lowering.relations[(context, node.id)]
            for context in lowering.members
            if node.id in lowering.members[context]
        )
        for node in lowering.cfg.nodes
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
        "%s: %d tracked fields, %d contexts, %d relations, %d rules",
        program.cfg.program,
        len(lowering.fields),
        len(lowering.members),
        len(relations),
        len(rules),
    )
    return HornSystem(rules, relations, _at(lowering), lowering.fields)
