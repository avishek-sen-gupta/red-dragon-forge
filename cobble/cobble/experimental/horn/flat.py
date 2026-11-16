"""Whether a node is reached, as one SMT formula: each context's CFG unrolled with every PERFORM inlined at its call, each loop cut at its header and each knot collapsed, holding the state it was entered in freed wherever it may write."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial, reduce

import networkx as nx
import z3
from cobble.dataflow.srccfg.cfg import Edge
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.context import (
    Context,
    perform_edge,
    performed,
    steps,
    top,
)
from cobble.experimental.horn.effects import Effect
from cobble.experimental.horn.loops import Cycles, Loops
from cobble.experimental.horn.lower import (
    UNSET,
    Lowering,
    edge_effect,
    edge_extras,
    edge_guard,
    edge_tag,
    entered_state,
    pgmiderr_guard,
    step_of,
)
from cobble.experimental.horn.reaches import Asked, asked_term
from cobble.experimental.horn.terms import any_of, bits, chosen, conjunction, equal
from cobble.experimental.horn.verdict import Verdict

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_MS = 180_000
ANSWERS: Mapping[str, Answer] = {"sat": Answer.SAT, "unsat": Answer.UNSAT}


@dataclass(frozen=True)
class Reached:
    """Whether a run gets to a node, and the state it has there if it does."""

    reach: z3.BoolRef
    state: tuple[z3.BitVecRef, ...]


@dataclass(frozen=True)
class Transfer:
    """One step as terms over the lowering's ``now`` variables and its own fresh
    ones: ``bundle`` holds the new value of each position in ``changed``, then the
    conditions to take the step; ``used`` are the variables it mentions, each as
    a position of ``now`` or -1 for a fresh one."""

    changed: tuple[int, ...]
    bundle: z3.BoolRef
    guards: int
    used: tuple[tuple[z3.ExprRef, int], ...]


Visited = tuple[
    Mapping[str, "Reached"], Mapping[str, tuple["Reached", ...]], tuple["Reached", ...]
]


@dataclass(frozen=True)
class Copy:
    """One inlined copy of a context: what reaching the target needs in it and in
    the ranges it performs, and the state at its end."""

    hits: tuple[Reached, ...]
    end: tuple[Reached, ...]


def _transfer(
    lowering: Lowering,
    tag: str,
    effect: Effect,
    guard: tuple[z3.BoolRef, ...],
    extras: tuple[z3.BoolRef, ...],
) -> Transfer:
    """The right-hand side of each ``after = ...`` the lowering writes; a
    position with none is free."""
    v = lowering.vars
    step = step_of(lowering, tag, effect)
    afters = frozenset(a.get_id() for a in v.after)
    defined = {
        term.arg(side).get_id(): term.arg(1 - side)
        for term in (*step.terms, *extras)
        for side in (0, 1)
        if term.arg(side).get_id() in afters
    }
    free = tuple(
        bits(f"free!{tag}!{k}", width)
        for k, width in enumerate(lowering.storage.widths)
    )
    after = tuple(
        defined.get(v.after[k].get_id(), free[k]) for k in range(len(v.after))
    )
    changed = tuple(
        k for k, term in enumerate(after) if term.get_id() != v.now[k].get_id()
    )
    parts = (*(after[k] for k in changed), *guard)
    bundle = _boolean(
        z3.Function(f"bundle!{tag}", *(p.sort() for p in parts), z3.BoolSort())(*parts)
    )
    position = {term.get_id(): k for k, term in enumerate(v.now)}
    used = tuple((c, position.get(c.get_id(), -1)) for c in _constants(bundle))
    return Transfer(changed, bundle, len(guard), used)


def _constants(term: z3.ExprRef) -> tuple[z3.ExprRef, ...]:
    """The uninterpreted constants ``term`` mentions, once each."""

    def walk(
        done: tuple[frozenset[int], tuple[z3.ExprRef, ...]], t: z3.ExprRef
    ) -> tuple[frozenset[int], tuple[z3.ExprRef, ...]]:
        seen, found = done
        if t.get_id() in seen:
            return done
        here = (seen | {t.get_id()}, (*found, t) if _uninterpreted(t) else found)
        return reduce(walk, t.children(), here)

    return reduce(walk, term.children(), (frozenset(), ()))[1]


def _uninterpreted(term: z3.ExprRef) -> bool:
    return z3.is_const(term) and term.decl().kind() == z3.Z3_OP_UNINTERPRETED


def _bitvec(term: z3.ExprRef) -> z3.BitVecRef:
    if isinstance(term, z3.BitVecRef):
        return term
    raise TypeError(f"{term} is not a bit-vector term")


@dataclass(frozen=True)
class Incoming:
    """Per node of a context, the steps into it and the PERFORMs that resume at it."""

    stepped: Mapping[str, tuple[Edge, ...]]
    resumed: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Flattening:
    lowering: Lowering
    loops: Mapping[Context, Loops]
    incoming: Mapping[Context, Incoming]
    arcs: Mapping[Context, tuple[tuple[str, str], ...]]
    edges: Mapping[Edge, Transfer]
    havocs: Mapping[frozenset[str], Transfer]
    target: str

    def instance(
        self, transfer: Transfer, state: Sequence[z3.BitVecRef], tag: str
    ) -> tuple[tuple[z3.BitVecRef, ...], tuple[z3.BoolRef, ...]]:
        pairs = tuple(
            (c, state[k] if k >= 0 else z3.Const(f"{c}@{tag}", c.sort()))
            for c, k in transfer.used
        )
        done = z3.substitute(transfer.bundle, *pairs) if pairs else transfer.bundle
        values = tuple(done.arg(k) for k in range(done.num_args()))
        count = len(transfer.changed)
        new = dict(zip(transfer.changed, values[:count], strict=True))
        return (
            tuple(_bitvec(new[k]) if k in new else state[k] for k in range(len(state))),
            tuple(_boolean(g) for g in values[count:]),
        )

    def copy(self, context: Context, entry: Reached, tag: str) -> Copy:
        units = {
            f"%knot{k}": knot.nodes for k, knot in enumerate(self.loops[context].knots)
        }
        visit = partial(self._visit, context, entry, tag, units)
        reached, _, hits = reduce(visit, self._order(context, units), ({}, {}, ()))
        end = (reached[context.end],) if context.end in reached else ()
        return Copy(hits, end)

    def _order(
        self, context: Context, units: Mapping[str, frozenset[str]]
    ) -> tuple[str, ...]:
        """The context's nodes, each knot as its one unit, in an order where every
        arrival but a back edge comes first."""
        loops = self.loops[context]
        unit = {n: name for name, nodes in units.items() for n in nodes}
        graph: nx.DiGraph[str] = nx.DiGraph()
        graph.add_nodes_from(unit.get(n, n) for n in self.lowering.members[context])
        graph.add_edges_from(
            (unit.get(a, a), unit.get(b, b))
            for a, b in self.arcs[context]
            if unit.get(a, a) != unit.get(b, b) and not loops.back(a, b)
        )
        return tuple(nx.topological_sort(graph))

    def _visit(
        self,
        context: Context,
        entry: Reached,
        tag: str,
        units: Mapping[str, frozenset[str]],
        done: Visited,
        name: str,
    ) -> Visited:
        reached, returned, hits = done
        nodes = units.get(name, frozenset({name}))
        incoming = tuple(
            arrival
            for node in sorted(nodes)
            for arrival in self._into(context, node, nodes, reached, returned, tag)
        )
        arrivals = (*incoming, entry) if context.entry in nodes else incoming
        merged = _merge(arrivals, entry.state, f"{tag}!{name}")
        at = self._held(self.loops[context], nodes, merged, f"{tag}!{name}")
        calls = {
            node: self._performed(node, edge, at[node], tag)
            for node in sorted(nodes)
            for edge in perform_edge(self.lowering.program.cfg, node)
        }
        inner = tuple(hit for copy in calls.values() for hit in copy.hits)
        own = tuple(at[n] for n in sorted(nodes) if n == self.target)
        ends = {node: copy.end for node, copy in calls.items()}
        return ({**reached, **at}, {**returned, **ends}, (*hits, *inner, *own))

    def _held(
        self, loops: Loops, nodes: frozenset[str], merged: Reached, tag: str
    ) -> Mapping[str, Reached]:
        """A loop's header, or every node of a knot, holds the state it was entered
        in with what the loop may write freed."""
        header = next(iter(nodes))
        freed = (
            nodes
            if len(nodes) > 1
            else (
                loops.headers[header].nodes if header in loops.headers else frozenset()
            )
        )
        if not freed:
            return {header: merged}
        after, _ = self.instance(self.havocs[freed], merged.state, tag)
        held = Reached(merged.reach, after)
        return {n: held for n in nodes}

    def _into(
        self,
        context: Context,
        node: str,
        unit: frozenset[str],
        reached: Mapping[str, Reached],
        returned: Mapping[str, tuple[Reached, ...]],
        tag: str,
    ) -> tuple[Reached, ...]:
        """Every way into ``node`` from outside ``unit`` but its loop's back edges:
        a step, or a PERFORM coming back."""
        loops = self.loops[context]
        incoming = self.incoming[context]
        stepped = tuple(
            self._stepped(edge, reached[edge.source], tag)
            for edge in incoming.stepped.get(node, ())
            if edge.source not in unit
            and edge.source in reached
            and not loops.back(edge.source, node)
        )
        resumed = tuple(
            end
            for source in incoming.resumed.get(node, ())
            if source not in unit
            and source in returned
            and not loops.back(source, node)
            for end in returned[source]
        )
        return (*stepped, *resumed)

    def _stepped(self, edge: Edge, source: Reached, tag: str) -> Reached:
        after, guard = self.instance(
            self.edges[edge], source.state, f"{tag}!{edge_tag(edge)}"
        )
        return Reached(conjunction(source.reach, *guard), after)

    def _performed(self, call: str, edge: Edge, at: Reached, tag: str) -> Copy:
        callee = performed(self.lowering.program.cfg, edge)
        position = {t.get_id(): k for k, t in enumerate(self.lowering.vars.now)}
        entered = tuple(
            at.state[position[term.get_id()]] if term.get_id() in position else term
            for term in entered_state(self.lowering, callee, call)
        )
        return self.copy(callee, Reached(at.reach, entered), f"{tag}>{call}")


def _incoming(cycles: Cycles, context: Context) -> Incoming:
    cfg = cycles.program.cfg
    members = cycles.members[context]
    edges = tuple(
        e
        for n in sorted(members)
        for e in steps(cfg, context, n)
        if e not in cycles.cut
    )
    resumes = tuple(
        (n, cfg.node(n).resume)
        for n in sorted(members)
        if perform_edge(cfg, n) and cfg.node(n).resume in members
    )
    return Incoming(
        {
            t: tuple(e for e in edges if e.target == t)
            for t in {e.target for e in edges}
        },
        {t: tuple(n for n, r in resumes if r == t) for t in {r for _, r in resumes}},
    )


def _boolean(term: z3.ExprRef) -> z3.BoolRef:
    if isinstance(term, z3.BoolRef):
        return term
    raise TypeError(f"{term} is not a boolean term")


def _merge(
    arrivals: Sequence[Reached], fallback: tuple[z3.BitVecRef, ...], tag: str
) -> Reached:
    """Any one arrival a run can take: each is chosen when it is reached and its
    own fresh selector says so, and the state is the first chosen one's. Choosing
    by reach alone would always take the first of two arrivals reached alike."""
    if not arrivals:
        return Reached(z3.BoolVal(False), fallback)
    if len(arrivals) == 1:
        return arrivals[0]
    chosen_ = tuple(
        conjunction(a.reach, _boolean(z3.Bool(f"pick!{tag}!{i}")))
        for i, a in enumerate(arrivals)
    )
    last = arrivals[-1].state
    state = tuple(
        reduce(
            lambda other, i: chosen(chosen_[i], arrivals[i].state[k], other),
            reversed(range(len(arrivals) - 1)),
            last[k],
        )
        for k in range(len(last))
    )
    return Reached(any_of(*chosen_), state)


def flattening(lowering: Lowering, target: str) -> Flattening:
    cfg = lowering.program.cfg
    cycles = Cycles(
        lowering.program,
        lowering.storage,
        lowering.members,
        lowering.effects,
        lowering.cut,
    )
    loops = {context: cycles.of(context) for context in lowering.members}
    edges = {
        edge: _transfer(
            lowering,
            edge_tag(edge),
            edge_effect(lowering, edge),
            (*edge_guard(lowering, edge), *pgmiderr_guard(lowering, edge)),
            edge_extras(lowering, edge),
        )
        for context in lowering.members
        for node in lowering.members[context]
        for edge in steps(cfg, context, node)
        if edge not in lowering.cut
    }
    v = lowering.vars
    havocs = {
        loop.nodes: _transfer(
            lowering,
            f"loop!{min(loop.nodes)}",
            loop.effect,
            (),
            tuple(
                equal(v.after[k], v.now[k])
                for k in range(len(lowering.storage.segments), len(v.now))
                if k not in loop.tail
            ),
        )
        for found in loops.values()
        for loop in (*found.headers.values(), *found.knots)
    }
    return Flattening(
        lowering,
        loops,
        {context: _incoming(cycles, context) for context in lowering.members},
        {context: cycles.arcs(context) for context in lowering.members},
        edges,
        havocs,
        target,
    )


def start(lowering: Lowering) -> Reached:
    """Any state, but no test has run and no range has been entered."""
    storage = lowering.storage
    first = len(storage.widths) - len(storage.entries) - len(storage.outcomes)
    widths = storage.widths
    state = tuple(
        (
            UNSET
            if first <= k < first + len(storage.outcomes)
            else (
                storage.entries[k - first - len(storage.outcomes)].unset()
                if k >= first + len(storage.outcomes)
                else bits(f"start!{k}", widths[k])
            )
        )
        for k in range(len(widths))
    )
    return Reached(z3.BoolVal(True), state)


@dataclass(frozen=True)
class Formula:
    """The target reached, as a disjunction over its inlined copies, asked of one
    solver so what it learns answering one question carries to the next."""

    lowering: Lowering
    hits: tuple[Reached, ...]
    solver: z3.Solver

    def ask(self, conditions: Sequence[Asked], clock: Callable[[], float]) -> Verdict:
        storage = self.lowering.storage
        goal = any_of(
            z3.BoolVal(False),
            *(
                conjunction(
                    hit.reach, *(asked_term(c, storage, hit.state) for c in conditions)
                )
                for hit in self.hits
            ),
        )
        question = _boolean(z3.FreshBool("asked"))
        self.solver.assert_exprs(z3.Implies(question, goal))
        begin = clock()
        answer = ANSWERS.get(str(self.solver.check(question)), Answer.UNKNOWN)
        return Verdict(answer, clock() - begin)


def formula(lowering: Lowering, target: str) -> Formula:
    flat = flattening(lowering, target)
    cfg = lowering.program.cfg
    copy = flat.copy(top(cfg), start(lowering), "top")
    logger.info("%s: %d copies of the target", target, len(copy.hits))
    solver = z3.SolverFor("QF_BV")
    solver.set(timeout=QUERY_TIMEOUT_MS)
    return Formula(lowering, copy.hits, solver)
