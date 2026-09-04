"""Reaching conditions: the guards along the paths that reach each node.

The condition language is the CFG. A guard is a sequence of ``(test node id, edge
polarity)`` pairs, and negation is the polarity -- which is why the ELSE arm of
``A AND B`` comes out as two paths rather than as one impossible conjunction. There
is no normal form here, no solver, and no simplifier: the tests were already
desugared into single-atom TEST nodes with a TRUE and a FALSE out-edge, so a path
is the condition.

Four things keep the walk finite and honest:

- **No node repeats on a path.** A loop body is walked once, so ``PERFORM UNTIL``
  yields the guard for entering the body and the guard for skipping it rather than
  an unbounded family of iterations. The price is paid on code that legitimately
  runs a node twice: a paragraph performed from inside the range of an active
  PERFORM of that same range -- overlapping ranges, which the standard leaves
  undefined -- reaches its own range end only on a second visit, so the tail of
  such a range comes out with no guards at all. Those nodes are named in
  ``Reaching.abandoned``, because "no guards" would otherwise read as dead code
  and dead code is the one thing they are not.
- **PERFORM returns are matched.** A ``PERFORM`` edge pushes the performing node; a
  ``RETURN`` edge is followed only back to a continuation of that node. Without it,
  a paragraph performed from a dozen places hands every one of its return edges to
  every call site and the guard sets stop meaning anything.
- **A PERFORM goes through the paragraph and comes back.** The CALL node's FLOW edge
  to the next statement is the node the paragraph's RETURN edge lands on, and a
  performed paragraph returns at its end rather than falling through to the next
  one, so each of those generic edges is walked only while the specific edge that
  duplicates it can still fire on this path. Walking both unconditionally would
  report everything after a call twice under one guard, and the duplicates would
  fill the cap and evict real paths; refusing both unconditionally would report
  reachable code as unreachable, which is the worse failure.
- **The cap is reported, and the report is closed forward.** ``MAX_PATHS`` bounds the
  guards kept per node; every node whose own arrivals were cut short is named in
  ``overflowed``, and ``truncated`` is that set closed forward over reachability,
  because a walk that was never expanded is missing from every node downstream of it
  too. An unreported
  truncation reads as "this field is written under exactly these conditions", which
  is a claim the walk did not establish.

Guards are recorded one per path, not deduplicated: two paths that happen to test
the same things in the same order are two paths, and collapsing walks would lose
the distinct perform stacks they carry. Callers that want the set of distinct
conditions can map ``guard_set`` over the tuple.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import accumulate, chain, groupby, pairwise, repeat
from operator import attrgetter
from types import MappingProxyType

from cobble.dataflow.srccfg.build import label_id
from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom, Cfg, Edge, EdgeKind
from cobble.dataflow.srccfg.desugar import DISPATCH_TRANSFER_CICS
from cobble.dataflow.srccfg.synthetic import (
    HANDLER_PREFIX,
    IGNORED,
    IMPLICIT_FIRST,
    SYSTEM_DEFAULT,
)

Guard = tuple[tuple[str, EdgeKind], ...]

MAX_PATHS = 64

POLARITIES = (EdgeKind.TRUE, EdgeKind.FALSE)

NO_GUARDS: Mapping[str, tuple[Guard, ...]] = MappingProxyType({})


@dataclass(frozen=True)
class Walk:
    """One partial path: where it is, the guard it carries, and what it may not redo.

    ``stack`` holds the performing nodes of the PERFORM edges taken and not yet
    returned from; ``seen`` holds the nodes already on this path.
    """

    node: str
    guard: Guard = ()
    stack: tuple[str, ...] = ()
    seen: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Reaching:
    """Per-node guards, and three different statements about what is missing.

    ``guards`` maps a node id to one guard per path that reached it. A node with one
    EMPTY guard is reached unconditionally; a node absent from the mapping was not
    reached by any path the walk took, which is NOT the same as unreachable -- see
    ``abandoned``.

    The three sets answer three different questions and none of them substitutes for
    another:

    - ``overflowed`` -- the nodes whose OWN arrivals hit ``max_paths``. This is where
      the cap, rather than the program, is rationing the answer, so it is what to
      read when deciding whether to raise the cap or ask a narrower question.
    - ``truncated`` -- ``overflowed`` closed forward over reachability. Every node
      here has a guard list that is a SUBSET of the real one, because a walk the cap
      refused is missing from every node after it as well. This is the set a consumer
      must check before reading a guard list as the complete set of conditions. It is
      emphatically not "skip this node": on a branch-heavy program it reaches nearly
      every node (measured 920 of 922 where ``overflowed`` was 234), which is a true
      statement about that program rather than a defect in the flag.
    - ``abandoned`` -- nodes with NO guards that nonetheless have a predecessor that
      HAS guards. The walk arrived next door and then gave up: the no-repeat rule
      consumed the only route on, which happens on overlapping PERFORM ranges. Their
      answer is empty because of the walk, not because of the program.

    So genuine dead code is **zero guards AND not in ``abandoned``**, and the two must
    not be collapsed in either direction. Reading ``abandoned`` as dead code reports
    live code as unreachable, the worst answer this pass can give. Reading dead code
    as ``abandoned`` throws away a finding worth having, because a paragraph that
    nothing performs and nothing falls into is a real thing to tell someone about.
    """

    guards: Mapping[str, tuple[Guard, ...]] = NO_GUARDS
    truncated: frozenset[str] = frozenset()
    overflowed: frozenset[str] = frozenset()
    abandoned: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Sweep:
    """The state of the search between two levels of the breadth-first walk."""

    guards: Mapping[str, tuple[Guard, ...]] = NO_GUARDS
    truncated: frozenset[str] = frozenset()
    frontier: tuple[Walk, ...] = ()


@dataclass(frozen=True)
class _Spread:
    """The state of the forward closure of ``truncated`` over reachability."""

    marked: frozenset[str] = frozenset()
    frontier: frozenset[str] = frozenset()


def entry_of(cfg: Cfg) -> str:
    """The first node the program runs: the implicit paragraph when the source has
    statements before its first paragraph, else the first paragraph's label."""
    implicit = label_id(IMPLICIT_FIRST)
    return implicit if implicit in cfg.node_ids else _first_id(cfg)


def _first_id(cfg: Cfg) -> str:
    return cfg.nodes[0].id if cfg.nodes else ""


def reaching_conditions(cfg: Cfg, max_paths: int = MAX_PATHS) -> Reaching:
    """Every node's guards, walked breadth-first from the program entry.

    Breadth-first is load-bearing under the cap: the guards that survive it are the
    short ones, which are the ones a reader can check against the source.
    """
    final = _sweep_to_empty(cfg, max_paths, _Sweep(frontier=_start(cfg)))
    return Reaching(
        guards=MappingProxyType(dict(final.guards)),
        truncated=_closed_forward(cfg, final.truncated),
        overflowed=final.truncated,
        abandoned=_abandoned(cfg, final.guards),
    )


def _abandoned(cfg: Cfg, guards: Mapping[str, tuple[Guard, ...]]) -> frozenset[str]:
    """The nodes with no guards that a guarded node leads to.

    The walk got next door and stopped, so "no path reaches this" is a claim about the
    walk and not about the program. Naming those nodes is what keeps the walk's known
    losses -- the no-repeat rule on an overlapping PERFORM range, most of all -- from
    reading as a confident report of dead code. What is left, zero guards with no
    guarded predecessor, is the dead code, and that is a finding rather than a gap.
    """
    return frozenset(
        node.id
        for node in cfg.nodes
        if not guards.get(node.id)
        and any(guards.get(edge.source) for edge in cfg.predecessors(node.id))
    )


def _closed_forward(cfg: Cfg, cut: frozenset[str]) -> frozenset[str]:
    """``cut`` plus everything reachable from it.

    A walk the cap refused was never expanded, so the nodes after it are short of
    that path too. Naming only the node that overflowed would let a reader treat a
    downstream node's guards as complete. The closure follows every edge kind,
    without the walk's matching rules: over-naming truncation costs a reader some
    caution, under-naming it costs them a wrong answer.
    """
    states = accumulate(
        repeat(None),
        lambda state, _: _spread(cfg, state),
        initial=_Spread(marked=cut, frontier=cut),
    )
    return next(state for state in states if not state.frontier).marked


def _spread(cfg: Cfg, state: _Spread) -> _Spread:
    reached = (
        frozenset(
            edge.target
            for node_id in state.frontier
            for edge in cfg.successors(node_id)
        )
        - state.marked
    )
    return _Spread(marked=state.marked | reached, frontier=reached)


def _start(cfg: Cfg) -> tuple[Walk, ...]:
    entry = entry_of(cfg)
    return (Walk(node=entry),) if entry else ()


def _sweep_to_empty(cfg: Cfg, max_paths: int, start: _Sweep) -> _Sweep:
    """Sweep whole levels until no walk is pending.

    The number of sweeps is the length of the longest path, which on a real member
    is in the hundreds -- so this is iteration over a lazy accumulation rather than
    recursion, which would exhaust the interpreter's stack on exactly the large
    members the pass exists for.
    """
    states = accumulate(
        repeat(None), lambda state, _: _swept(cfg, max_paths, state), initial=start
    )
    return next(state for state in states if not state.frontier)


def _swept(cfg: Cfg, max_paths: int, state: _Sweep) -> _Sweep:
    """One level: admit what the cap has room for, name what it did not, step on."""
    arrivals = _by_node(state.frontier)
    admitted = {
        node_id: walks[: _room(state.guards, node_id, max_paths)]
        for node_id, walks in arrivals.items()
    }
    return _Sweep(
        guards={**state.guards, **_recorded(state.guards, admitted)},
        truncated=state.truncated | _overflowed(arrivals, admitted),
        frontier=tuple(
            chain.from_iterable(
                _next_walks(cfg, walk)
                for walk in chain.from_iterable(admitted.values())
            )
        ),
    )


def _by_node(walks: tuple[Walk, ...]) -> Mapping[str, tuple[Walk, ...]]:
    """The level's walks grouped by the node they arrived at, arrival order kept."""
    ordered = sorted(walks, key=attrgetter("node"))
    return {
        node_id: tuple(group)
        for node_id, group in groupby(ordered, key=attrgetter("node"))
    }


def _room(guards: Mapping[str, tuple[Guard, ...]], node_id: str, max_paths: int) -> int:
    return max(max_paths - len(guards.get(node_id, ())), 0)


def _recorded(
    guards: Mapping[str, tuple[Guard, ...]],
    admitted: Mapping[str, tuple[Walk, ...]],
) -> Mapping[str, tuple[Guard, ...]]:
    return {
        node_id: (*guards.get(node_id, ()), *(walk.guard for walk in walks))
        for node_id, walks in admitted.items()
        if walks
    }


def _overflowed(
    arrivals: Mapping[str, tuple[Walk, ...]],
    admitted: Mapping[str, tuple[Walk, ...]],
) -> frozenset[str]:
    """The nodes this level had more arrivals for than the cap left room for."""
    return frozenset(
        node_id
        for node_id, walks in arrivals.items()
        if len(walks) > len(admitted.get(node_id, ()))
    )


def _next_walks(cfg: Cfg, walk: Walk) -> tuple[Walk, ...]:
    seen = walk.seen | {walk.node}
    return tuple(
        _advance(walk, edge, seen)
        for edge in cfg.successors(walk.node)
        if edge.target not in seen and _passable(cfg, walk, edge, seen)
    )


def _passable(cfg: Cfg, walk: Walk, edge: Edge, seen: frozenset[str]) -> bool:
    """Whether this path may take this edge.

    A RETURN edge belongs to one call site. Taking another call site's return joins
    that site's guard onto this path, and a paragraph performed from a dozen places
    would turn every guard set into the union of all of them. The legitimate targets
    are the FLOW successors of the node on top of the stack, because that is what
    build.py attached the return edges to.

    The other two rules share one invariant: where the graph offers both a specific
    edge and a generic one to the same place, the generic edge is refused only while
    the specific one can still fire on THIS path. Not while it merely exists -- a
    specific edge that can never fire again would leave the walk with no way out, and
    a walk that dies reports live code as unreachable.

    - A CALL node keeps a FLOW edge to the statement after it AND a PERFORM edge into
      the paragraph, and the paragraph's RETURN edge lands on that same FLOW target.
      Walking both reaches everything after the call twice under one guard, and ten
      calls in a row would report 2^10 duplicate paths. So FLOW out of a CALL node is
      refused while a RETURN onto its target is still pending; see
      ``_return_pending``.
    - A performed paragraph returns at its end; it does not fall through to the next
      paragraph. So a FALLTHRU edge is refused where the frame on top of the stack
      can still return from here. It is kept where the frame cannot -- a paragraph in
      the middle of a PERFORM A THRU B range reaches the next one by falling through,
      and control arriving with no frame at all falls through as written.

    Refusing that FALLTHRU is not cosmetic. Measured on a synthetic 922-node program
    of one driver paragraph performing forty others, following it left 39 nodes with
    no guards at all: the fall-through paths filled the cap and evicted the returns
    the driver's later statements are only reachable by. Over-approximating is the
    safe direction only while the cap is not the thing rationing the answer.
    """
    if edge.kind is EdgeKind.RETURN:
        return bool(walk.stack) and edge.target in _continuations(cfg, walk.stack[-1])
    if edge.kind is EdgeKind.FLOW:
        return not _performs(cfg, walk.node, seen) or not _return_pending(
            cfg, edge, seen
        )
    if edge.kind is EdgeKind.FALLTHRU:
        return not _returns_from(cfg, walk, seen)
    return True


def _continuations(cfg: Cfg, call_id: str) -> frozenset[str]:
    return frozenset(
        edge.target for edge in cfg.successors(call_id) if edge.kind is EdgeKind.FLOW
    )


def _performs(cfg: Cfg, node_id: str, seen: frozenset[str]) -> bool:
    """Whether this node has a PERFORM edge this path can still follow."""
    return any(
        edge.kind is EdgeKind.PERFORM and edge.target not in seen
        for edge in cfg.successors(node_id)
    )


def _return_pending(cfg: Cfg, edge: Edge, seen: frozenset[str]) -> bool:
    """Whether a RETURN onto this edge's target can still fire on this path.

    A RETURN is spent when the range end it leaves from is already on the path: the
    no-repeat rule bars that node, so this walk will never take that return, and the
    CALL node's FLOW edge is the only way past the call. That is not a corner case.
    ``PERFORM PB. PERFORM PA THRU PB.`` returns to the second call site from PB#end;
    the second call then enters PA, whose end has no return edge of its own and whose
    fall-through to PB is barred because PB is already on the path. Refusing FLOW
    there loses every statement after the second call.

    The second clause is a graph-level dead-end test, and only that: a node with no
    in-edges at all is a node nothing in the graph reaches, so a performed paragraph
    whose only statement is a GO TO never arrives at its own end and the return
    hanging off that end can never fire. It is not a general guarantee that the return
    is live. A return whose source has predecessors but which THIS walk can no longer
    get to -- because ``seen`` blocks the only route to it -- still counts as pending,
    and the FLOW edge is still refused. That is where the walk's remaining loss lives:
    it is the overlapping-PERFORM-range case named under the no-repeat rule in the
    module docstring, it cannot be decided here (at the call, the range end is still
    graph-reachable; the blockage only appears later, once the interior has been
    consumed), and it is reported through ``Reaching.abandoned`` rather than fixed.
    """
    return any(
        back.source not in seen and bool(cfg.predecessors(back.source))
        for back in cfg.predecessors(edge.target)
        if back.kind is EdgeKind.RETURN
    )


def _returns_from(cfg: Cfg, walk: Walk, seen: frozenset[str]) -> bool:
    """Whether the frame on top of the stack can return from this node."""
    if not walk.stack:
        return False
    continuations = _continuations(cfg, walk.stack[-1]) - seen
    return any(
        edge.kind is EdgeKind.RETURN and edge.target in continuations
        for edge in cfg.successors(walk.node)
    )


def _advance(walk: Walk, edge: Edge, seen: frozenset[str]) -> Walk:
    return Walk(
        node=edge.target,
        guard=_extended(walk, edge),
        stack=_stack(walk, edge),
        seen=seen,
    )


def _extended(walk: Walk, edge: Edge) -> Guard:
    if edge.kind in POLARITIES:
        return (*walk.guard, (edge.source, edge.kind))
    return walk.guard


def _stack(walk: Walk, edge: Edge) -> tuple[str, ...]:
    """A PERFORM pushes the node that performed; a RETURN pops the frame it matched."""
    if edge.kind is EdgeKind.PERFORM:
        return (*walk.stack, edge.source)
    if edge.kind is EdgeKind.RETURN:
        return walk.stack[:-1]
    return walk.stack


def guards_of(reaching: Reaching, node_id: str) -> tuple[Guard, ...]:
    """A node's guards. Empty means no path reached it, which is a real answer -- so
    an unguarded node has one EMPTY guard rather than no guards."""
    return reaching.guards.get(node_id, ())


def guard_set(guard: Guard) -> frozenset[tuple[str, EdgeKind]]:
    """A guard without its order, for asking whether two writes are guarded alike."""
    return frozenset(guard)


def guard_text(cfg: Cfg, guard: Guard) -> tuple[str, ...]:
    """One readable term per step, FALSE steps negated."""
    return tuple(_term(cfg, node_id, kind) for node_id, kind in guard)


def _term(cfg: Cfg, node_id: str, kind: EdgeKind) -> str:
    """A predicate this pass could not decompose still renders as a term.

    Dropping it would strengthen the guard -- claiming the node is reached under
    fewer conditions than it is -- so an unresolved atom keeps its place and says so.
    """
    text = _atom_text(cfg.node(node_id).atom)
    return text if kind is EdgeKind.TRUE else f"NOT ({text})"


def _atom_text(atom: Atom) -> str:
    """The atom's text, marked when the atom was not resolved.

    The mark is on ``resolved``, not on empty text: the desugaring emits unresolved
    atoms that read like predicates -- an ON EXCEPTION arm, a SEARCH whose outcome is
    unknown -- and rendering those as though they were understood is the same
    dishonesty as dropping them, just quieter.
    """
    if atom.resolved:
        return atom.text
    detail = atom.text.strip()
    if not detail or detail == UNRESOLVED.text:
        return UNRESOLVED.text
    return f"{UNRESOLVED.text}: {detail}"


@dataclass(frozen=True)
class Definition:
    """One write: the node that did it and the field it wrote.

    field is the literal write text, subscript and reference modification included
    (e.g., 'WS-TAB(1)', 'WS-FIELD(1:4)'). Match with base_field rather than == if
    you need to find all writes to a base name."""

    node: str
    field: str


Defs = frozenset[Definition]

HANDLER_SEPARATOR = ", "


def base_field(field: str) -> str:
    """The base name: strip subscripts and reference modification.

    'WS-TAB(1)' -> 'WS-TAB', 'WS-FIELD(1:4)' -> 'WS-FIELD', 'WS-X' -> 'WS-X'.
    Use this to match definitions by base name when querying reaching_definitions."""
    paren = field.find("(")
    return field[:paren] if paren >= 0 else field


def definitions_of(cfg: Cfg) -> Mapping[str, Defs]:
    """The gen set: what each node writes."""
    return {
        node.id: frozenset(Definition(node=node.id, field=name) for name in node.writes)
        for node in cfg.nodes
    }


def reaching_definitions(cfg: Cfg) -> Mapping[str, Defs]:
    """A gen/kill fixpoint. Not the path walk: one definition reached by four paths
    is one definition, and a per-path answer would report it four times.

    Field matching is by exact literal text: a write to WS-TAB(1) generates a definition
    with field='WS-TAB(1)', not field='WS-TAB'. Use base_field to match by base name."""
    generated = definitions_of(cfg)
    start = {node.id: frozenset() for node in cfg.nodes}
    states = accumulate(
        repeat(None),
        lambda incoming, _: _stepped(cfg, incoming, generated),
        initial=start,
    )
    return next(later for earlier, later in pairwise(states) if earlier == later)


def _stepped(
    cfg: Cfg, incoming: Mapping[str, Defs], generated: Mapping[str, Defs]
) -> Mapping[str, Defs]:
    """One sweep: recompute every node's in-set from its predecessors' out-sets."""
    return {node_id: _joined(cfg, node_id, incoming, generated) for node_id in incoming}


def _joined(
    cfg: Cfg,
    node_id: str,
    incoming: Mapping[str, Defs],
    generated: Mapping[str, Defs],
) -> Defs:
    """Union the out-sets of all predecessors."""
    return frozenset(
        chain.from_iterable(
            _out_of(edge.source, incoming, generated)
            for edge in cfg.predecessors(node_id)
        )
    )


def _out_of(
    node_id: str, incoming: Mapping[str, Defs], generated: Mapping[str, Defs]
) -> Defs:
    """Gen/kill: definitions reaching this node, minus what it kills, plus what it generates.

    A subscripted or reference-modified write (WS-TAB(1), WS-FIELD(1:4)) kills only
    itself, not the base name or other subscripts. Over-approximate on gen, never on kill.
    """
    written = {definition.field for definition in generated.get(node_id, frozenset())}
    survived = frozenset(
        definition
        for definition in incoming.get(node_id, frozenset())
        if definition.field not in written
    )
    return survived | generated.get(node_id, frozenset())


@dataclass(frozen=True)
class Use:
    """One read: the node and field, and every definition reaching it."""

    node: str
    field: str
    definitions: Defs = frozenset()


def def_use(cfg: Cfg) -> tuple[Use, ...]:
    """Every read and the definitions reaching it.

    Matches on both exact field name and base name: a read of WS-TAB sees definitions
    of both WS-TAB and WS-TAB(1). Handler reads (%HANDLER[ANY]) are NOT resolved here;
    use live_handlers for those."""
    incoming = reaching_definitions(cfg)
    return tuple(
        Use(
            node=node.id,
            field=name,
            definitions=frozenset(
                d
                for d in incoming.get(node.id, frozenset())
                if base_field(d.field) == base_field(name)
            ),
        )
        for node in cfg.nodes
        for name in node.reads
    )


def writers_of(cfg: Cfg, field: str) -> tuple[str, ...]:
    """Every node that writes this field, in source order.

    Matches on both exact field name and base name: writers_of("WS-TAB") returns nodes
    writing WS-TAB, WS-TAB(1), WS-TAB(WS-I), and WS-TAB(1:4). A subscripted query is
    answered by base name, so writers_of("WS-TAB(1)") also returns nodes writing WS-TAB(2);
    use def_use if you need the qualifier."""
    base = base_field(field)
    return tuple(
        node.id
        for node in cfg.nodes
        if any(base_field(name) == base for name in node.writes)
    )


def live_handlers(cfg: Cfg) -> Mapping[str, tuple[str, ...]]:
    """The paragraphs a raise at each dispatch node can reach.

    Any %HANDLER[...] definition reaching the dispatch is a candidate, whatever the
    condition: the dispatch reads %HANDLER[ANY] because the CFG does not model which
    condition a command raises."""
    incoming = reaching_definitions(cfg)
    return {
        node.id: _targets(cfg, incoming.get(node.id, frozenset()))
        for node in cfg.nodes
        if node.transfer == DISPATCH_TRANSFER_CICS
    }


def _targets(cfg: Cfg, definitions: Defs) -> tuple[str, ...]:
    """The paragraph names to which a dispatch can transfer.

    Over-approximates: takes every read from any node holding a surviving handler
    definition. So HANDLE CONDITION MAPFAIL(H-M) ERROR(H-E) followed by HANDLE
    CONDITION MAPFAIL(H-M2) yields H-E, H-M, H-M2 even though H-M was killed. The
    alternative -- pairing writes[i] with reads[i] positionally -- breaks the moment
    Task 10's _dedupe collapses two conditions armed to the same paragraph, or anything
    else re-orders the node's field lists. Over-approximating a handler target is safe;
    silently dropping one is not."""
    return tuple(
        sorted(
            {
                value
                for definition in definitions
                if definition.field.startswith(HANDLER_PREFIX)
                for value in cfg.node(definition.node).reads
                if value not in (IGNORED, SYSTEM_DEFAULT)
            }
        )
    )


def with_handler_edges(cfg: Cfg) -> Cfg:
    """Resolve every dispatch node, so a walk reaches the handler paragraph and an
    assignment there carries the guard of the command that raised.

    Unresolvable handler targets (armed but the paragraph does not exist) are kept
    visible on the dispatch node's target field rather than silently dropped.

    Applying this twice is applying it once: the edges it would add a second time are
    already present and are filtered out. It runs in the corpus build, so a consumer
    that reads an artefact and applies it again -- reasonably, having no way to know --
    must not end up with a doubled GOTO out of every dispatch, which would double the
    paths out of it and bring the guard cap down that much sooner."""
    handlers = live_handlers(cfg)
    added = tuple(
        edge
        for node_id, targets in handlers.items()
        for target in targets
        if label_id(target) in cfg.node_ids
        for edge in (Edge(source=node_id, target=label_id(target), kind=EdgeKind.GOTO),)
        if edge not in cfg.edges
    )
    unresolved_by_node = {
        node_id: tuple(t for t in targets if label_id(t) not in cfg.node_ids)
        for node_id, targets in handlers.items()
    }
    updated_nodes = tuple(
        (
            node
            if node.id not in unresolved_by_node or not unresolved_by_node[node.id]
            else replace(
                node, target=HANDLER_SEPARATOR.join(unresolved_by_node[node.id])
            )
        )
        for node in cfg.nodes
    )
    return (
        cfg
        if not added and not any(unresolved_by_node.values())
        else Cfg(program=cfg.program, nodes=updated_nodes, edges=(*cfg.edges, *added))
    )
