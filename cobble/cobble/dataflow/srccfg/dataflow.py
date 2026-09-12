"""Reaching conditions: the guards along the paths that reach each node.

The condition language is the CFG. A guard is a sequence of ``(test node id, edge
polarity)`` pairs, and negation is the polarity -- which is why the ELSE arm of
``A AND B`` comes out as two paths rather than as one impossible conjunction. There
is no normal form here, no solver, and no simplifier: the tests were already
desugared into single-atom TEST nodes with a TRUE and a FALSE out-edge, so a path
is the condition.

Four things keep the walk finite and honest:

- **No node repeats within an ACTIVATION.** An activation is one entry into a
  paragraph: the frame a PERFORM opens, or the straight-line run that fell into it.
  Inside one, a loop body is walked once, so ``PERFORM UNTIL`` yields the guard for
  entering the body and the guard for skipping it rather than an unbounded family of
  iterations. Across activations the rule does not apply, because a paragraph
  performed on its own and then fallen through inside a ``PERFORM A THRU C`` range
  genuinely runs twice, and barring the second run stranded the tail of the range --
  measured at 94% of a synthetic program's nodes reporting no guards at all. What
  bounds the stack instead is that a paragraph may not be performed from inside
  itself, which is also what the standard leaves undefined.
- **PERFORM returns are matched.** A ``PERFORM`` edge pushes a frame holding the
  performing node; a ``RETURN`` edge is followed only back to a continuation of that
  frame's node. Without it, a paragraph performed from a dozen places hands every one
  of its return edges to every call site and the guard sets stop meaning anything.
- **A PERFORM goes through the paragraph and comes back -- and where it did not, the
  walk resumes.** The CALL node's FLOW edge to the next statement is the node the
  paragraph's RETURN edge lands on, and a performed paragraph returns at its end
  rather than falling through to the next one, so each of those generic edges is
  walked only while the specific edge that duplicates it can still fire on this path.
  Walking both unconditionally would report everything after a call twice under one
  guard, and the duplicates would fill the cap and evict real paths. But refusing the
  generic edge PREDICTS the specific one, and the cap can falsify that prediction
  silently: the walk runs out of room inside the paragraph, never reaches its end, no
  RETURN fires, and the refused edge was the only way past the call. So a second pass
  takes those edges after all, from the frames that reached the call, and names the
  nodes it recovered in ``resumed``.
- **The cap is reported, and the report is closed forward.** ``MAX_PATHS`` bounds the
  guards kept per node; every node whose own arrivals were cut short is named in
  ``overflowed``, and ``truncated`` is that set closed forward over reachability,
  because a walk that was never expanded is missing from every node downstream of it
  too. An unreported
  truncation reads as "this field is written under exactly these conditions", which
  is a claim the walk did not establish.

Guards are deduplicated per node, in first-seen order: a guard is a condition, and the
same condition arriving twice is one fact about the program, not two. What the cap
rations is arrivals, counted separately -- because several activations of one paragraph
reach a node under one condition, and rationing recorded guards instead would let a
paragraph performed from everywhere be walked without limit.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import accumulate, chain, groupby, pairwise, repeat
from operator import attrgetter
from types import MappingProxyType

_log = logging.getLogger(__name__)

from cobble.dataflow.srccfg.build import label_id
from cobble.dataflow.srccfg.cfg import (
    UNRESOLVED,
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
)
from cobble.dataflow.srccfg.conditions import VALUE_OPS
from cobble.dataflow.srccfg.desugar import DISPATCH_TRANSFER_CICS
from cobble.dataflow.srccfg.synthetic import (
    HANDLER_PREFIX,
    IGNORED,
    IMPLICIT_FIRST,
    SYSTEM_DEFAULT,
    is_synthetic,
)

Guard = tuple[tuple[str, EdgeKind], ...]

MAX_PATHS = 64

POLARITIES = (EdgeKind.TRUE, EdgeKind.FALSE)

NO_GUARDS: Mapping[str, tuple[Guard, ...]] = MappingProxyType({})


@dataclass(frozen=True)
class _Frame:
    """One PERFORM taken and not yet returned from: the call, the paragraph, the caller.

    ``seen`` is the caller's own ``seen`` at the moment of the call, put aside so the
    RETURN can restore it. ``target`` is what the recursion guard compares against.
    """

    call: str
    target: str
    seen: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Walk:
    """One partial path: where it is, the guard it carries, and what it may not redo.

    ``stack`` holds a frame per PERFORM edge taken and not yet returned from; ``seen``
    holds the nodes already walked IN THE CURRENT ACTIVATION -- the innermost frame's,
    not the path's. That distinction is the walk's execution model. A paragraph runs
    once per activation, and two activations of it are two runs: ``PERFORM PB`` and a
    later ``PERFORM PA THRU PC`` whose range covers PB both execute PB, and a set
    shared across the whole path would bar the second and strand the range.
    """

    node: str
    guard: Guard = ()
    stack: tuple[_Frame, ...] = ()
    seen: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Reaching:
    """Per-node guards, and four different statements about how far to trust them.

    ``guards`` maps a node id to the DISTINCT guards of the paths that reached it, in the
    order they were first seen. A node with one EMPTY guard is reached unconditionally; a
    node absent from the mapping was not reached by any path the walk took, which is NOT
    the same as unreachable -- see ``abandoned``.

    The four sets answer four different questions and none of them substitutes for
    another. The first three say a guard list may be too SMALL; the last says one node's
    may be too large:

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
    - ``abandoned`` -- nodes with NO guards that a guarded node leads to, closed
      forward through the unguarded ones. The walk arrived next door and then gave up:
      the no-repeat rule consumed the only route on, which happens on overlapping
      PERFORM ranges. Their answer is empty because of the walk, not because of the
      program. Closing forward is what makes the set usable -- the nodes with a guarded
      neighbour are only the boundary of the region the walk lost, and naming the
      boundary alone reported the rest of the region as dead code.
    - ``resumed`` -- the call continuations the walk reached only by taking a PERFORM's
      FLOW edge after no RETURN ever arrived; see ``_resumed_to_fixpoint``. Each carries
      the guard of the call, which is what a paragraph that returns hands back, and a
      guess for a paragraph that never returns at all. The imprecision travels downstream
      from these nodes without being named there: naming the closure would flag most of a
      program, which tells a reader nothing, whereas the seeds are few and each one is a
      question a reader can settle by looking at one paragraph.

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
    resumed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Sweep:
    """The state of the search between two levels of the breadth-first walk.

    ``arrivals`` counts walks admitted per node, which is what the cap rations. It is
    not ``len(guards[node])``: several activations of one paragraph reach it under the
    same condition and record ONE guard between them, so counting the recorded guards
    instead would let a shared paragraph be walked without limit.

    ``deferred`` holds the call continuations the walk refused on the prediction that a
    RETURN would reach them, and ``resumed`` the nodes a later pass seeded from that list
    because none did. Both survive across sweeps, because the prediction can only be
    judged once a whole sweep has come to nothing.
    """

    guards: Mapping[str, tuple[Guard, ...]] = NO_GUARDS
    arrivals: Mapping[str, int] = MappingProxyType({})
    truncated: frozenset[str] = frozenset()
    frontier: tuple[Walk, ...] = ()
    deferred: tuple[Walk, ...] = ()
    resumed: frozenset[str] = frozenset()


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
    final = _resumed_to_fixpoint(
        cfg, max_paths, _sweep_to_empty(cfg, max_paths, _Sweep(frontier=_start(cfg)))
    )
    return Reaching(
        guards=MappingProxyType(dict(final.guards)),
        truncated=_closed_forward(cfg, final.truncated),
        overflowed=final.truncated,
        abandoned=_abandoned(cfg, final.guards),
        resumed=final.resumed,
    )


def _resumed_to_fixpoint(cfg: Cfg, max_paths: int, swept: _Sweep) -> _Sweep:
    """Sweep again from every call continuation the search left unreached, until none is.

    Refusing a call's FLOW edge predicts that the paragraph's RETURN will reach the
    continuation instead. The cap can falsify that prediction without saying so: enough
    paths inside the paragraph and the walk never gets to its end, no RETURN fires, and
    the one edge that led past the call was refused on the strength of a return that
    never came. The loss is not local. Everything after the call is zeroed, including
    the returns of the calls that CONTAIN this one, so a partial answer inside a
    paragraph becomes a total answer of nothing for the rest of the program -- measured
    on a real 1692-node member as 55 of 114 paragraphs reporting no guards at all,
    cascading from one call whose paragraph hit the cap.

    So each round takes the continuations still unreached and walks on from them, with
    the frames and guard of the walk that reached the call. A resumed continuation's
    guard is the call's, which is the right answer whenever the paragraph would have
    returned -- and a guess whenever it genuinely never returns, which is why the seeds
    are named in ``resumed`` rather than folded in silently.

    Each round either strands nothing and stops, or seeds at least one node it has never
    seeded before, so the number of rounds is bounded by the node count. Seeding a node
    only once is what guarantees that: a node the cap has no room left for stays
    unreached however often it is offered, and without the ``resumed`` set it would be
    offered forever.
    """
    states = accumulate(
        repeat(None), lambda state, _: _resumed(cfg, max_paths, state), initial=swept
    )
    return next(state for state in states if not _stranded(state))


def _stranded(state: _Sweep) -> tuple[Walk, ...]:
    """The deferred walks whose continuation is still unreached and never yet seeded."""
    return tuple(
        walk
        for walk in state.deferred
        if not state.guards.get(walk.node) and walk.node not in state.resumed
    )


def _resumed(cfg: Cfg, max_paths: int, state: _Sweep) -> _Sweep:
    stranded = _stranded(state)
    return _sweep_to_empty(
        cfg,
        max_paths,
        replace(
            state,
            frontier=stranded,
            resumed=state.resumed | frozenset(walk.node for walk in stranded),
        ),
    )


def _abandoned(cfg: Cfg, guards: Mapping[str, tuple[Guard, ...]]) -> frozenset[str]:
    """Every node with no guards that a guarded node leads to, however far downstream.

    The walk got next door and stopped, so "no path reaches this" is a claim about the
    walk and not about the program. Naming those nodes is what keeps the walk's known
    losses -- the no-repeat rule on an overlapping PERFORM range, most of all -- from
    reading as a confident report of dead code. What is left, zero guards with no
    guarded node leading to them at all, is the dead code, and that is a finding
    rather than a gap.

    Closing forward is what makes that split sound. The nodes where a guarded
    predecessor sits next door are only the BOUNDARY of the region the walk lost;
    everything the boundary leads on to has no guards for exactly the same reason and
    no guarded neighbour to say so. Naming the boundary alone reported the rest as
    dead: on a synthetic program whose range end the walk could not reach, one of the
    paragraph's three nodes was named and the other two were called unreachable.
    """
    return _closed_forward_through(
        cfg,
        guards,
        frozenset(
            node.id
            for node in cfg.nodes
            if not guards.get(node.id)
            and any(guards.get(edge.source) for edge in cfg.predecessors(node.id))
        ),
    )


def _closed_forward_through(
    cfg: Cfg, guards: Mapping[str, tuple[Guard, ...]], boundary: frozenset[str]
) -> frozenset[str]:
    """``boundary`` plus what it reaches WITHOUT passing through a guarded node.

    Stopping at guarded nodes is the point: a guarded node's own successors were
    walked, so their emptiness is not this region's doing and would be a different
    claim about a different failure.
    """
    states = accumulate(
        repeat(None),
        lambda state, _: _spread_unguarded(cfg, guards, state),
        initial=_Spread(marked=boundary, frontier=boundary),
    )
    return next(state for state in states if not state.frontier).marked


def _spread_unguarded(
    cfg: Cfg, guards: Mapping[str, tuple[Guard, ...]], state: _Spread
) -> _Spread:
    reached = (
        frozenset(
            edge.target
            for node_id in state.frontier
            for edge in cfg.successors(node_id)
            if not guards.get(edge.target)
        )
        - state.marked
    )
    return _Spread(marked=state.marked | reached, frontier=reached)


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
        node_id: walks[: _room(state.arrivals, node_id, max_paths)]
        for node_id, walks in arrivals.items()
    }
    walked = tuple(chain.from_iterable(admitted.values()))
    return replace(
        state,
        guards={**state.guards, **_recorded(state.guards, admitted)},
        arrivals=_counted(state.arrivals, admitted),
        truncated=state.truncated | _overflowed(arrivals, admitted),
        frontier=tuple(chain.from_iterable(_next_walks(cfg, walk) for walk in walked)),
        deferred=_kept(
            state.deferred,
            tuple(chain.from_iterable(_deferred_walks(cfg, walk) for walk in walked)),
        ),
    )


def _kept(deferred: tuple[Walk, ...], refused: tuple[Walk, ...]) -> tuple[Walk, ...]:
    """The deferral list after this level, without duplicates.

    The same call reached under the same guard by two activations defers the same walk
    twice, and the list lives for the whole search -- so deduplicating here is what keeps
    it from growing with the walk rather than with the program.
    """
    return tuple(dict.fromkeys((*deferred, *refused)))


def _by_node(walks: tuple[Walk, ...]) -> Mapping[str, tuple[Walk, ...]]:
    """The level's walks grouped by the node they arrived at, arrival order kept."""
    ordered = sorted(walks, key=attrgetter("node"))
    return {
        node_id: tuple(group)
        for node_id, group in groupby(ordered, key=attrgetter("node"))
    }


def _room(arrivals: Mapping[str, int], node_id: str, max_paths: int) -> int:
    return max(max_paths - arrivals.get(node_id, 0), 0)


def _counted(
    arrivals: Mapping[str, int], admitted: Mapping[str, tuple[Walk, ...]]
) -> Mapping[str, int]:
    return {
        **arrivals,
        **{
            node_id: arrivals.get(node_id, 0) + len(walks)
            for node_id, walks in admitted.items()
            if walks
        },
    }


def _recorded(
    guards: Mapping[str, tuple[Guard, ...]],
    admitted: Mapping[str, tuple[Walk, ...]],
) -> Mapping[str, tuple[Guard, ...]]:
    """The guard lists after this level, each holding every DISTINCT guard recorded so
    far in the order it was first seen.

    A guard is a condition, and a condition repeated says nothing the first one did
    not. Deduping matters most where it is least visible: a paragraph performed from
    forty sites is reached unconditionally by all forty, and forty copies of the empty
    guard is what a reader has to wade through to learn one fact.
    """
    return {
        node_id: _distinct(guards.get(node_id, ()), tuple(walk.guard for walk in walks))
        for node_id, walks in admitted.items()
        if walks
    }


def _distinct(
    recorded: tuple[Guard, ...], arriving: tuple[Guard, ...]
) -> tuple[Guard, ...]:
    return (
        *recorded,
        *dict.fromkeys(guard for guard in arriving if guard not in recorded),
    )


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
    """Every edge this path may take from here, with the activation's no-repeat rule.

    A PERFORM edge is exempt from that rule and answers to the recursion guard instead.
    It opens a new activation, so what the caller has already walked says nothing about
    whether the paragraph runs: ``PERFORM PB`` twice in a row runs PB twice.
    """
    seen = walk.seen | {walk.node}
    return tuple(
        _advance(walk, edge, seen)
        for edge in cfg.successors(walk.node)
        if _repeatable(walk, edge, seen) and _passable(cfg, walk, edge, seen)
    )


def _deferred_walks(cfg: Cfg, walk: Walk) -> tuple[Walk, ...]:
    """The continuations this walk was refused because a RETURN was predicted to reach
    them: the same walks ``_next_walks`` would have yielded had the prediction not been
    made, kept aside in case it turns out no RETURN ever arrives.

    Keeping the WALK and not just the node id is the whole point. A resumed walk has to
    carry the frames that reached the call, or it lands in the caller with an empty stack
    and the walk goes wrong in both directions at once -- the caller's own paragraph end
    falls through to the next paragraph instead of returning, and the return it should
    have taken is refused for belonging to no frame.
    """
    seen = walk.seen | {walk.node}
    return tuple(
        _advance(walk, edge, seen)
        for edge in cfg.successors(walk.node)
        if _duplicates_a_return(cfg, walk, edge) and _repeatable(walk, edge, seen)
    )


def _repeatable(walk: Walk, edge: Edge, seen: frozenset[str]) -> bool:
    if edge.kind is EdgeKind.PERFORM:
        return _not_already_active(walk, edge)
    return edge.target not in seen


def _passable(cfg: Cfg, walk: Walk, edge: Edge, seen: frozenset[str]) -> bool:
    """Whether this path may take this edge: every rule that governs its kind agrees.

    Each rule below governs one edge kind and passes every other kind through, so the
    conjunction is the whole policy and an edge kind no rule names is passable.

    The last two share one invariant: where the graph offers both a specific edge and
    a generic one to the same place, the generic edge is refused only while the
    specific one can still fire on THIS path. Not while it merely exists -- a specific
    edge that can never fire again would leave the walk with no way out, and a walk
    that dies reports live code as unreachable.
    """
    return (
        _returns_to_its_own_call_site(cfg, walk, edge)
        and not _duplicates_a_return(cfg, walk, edge)
        and _not_a_fallthrough_a_return_will_take(cfg, walk, edge, seen)
    )


def _returns_to_its_own_call_site(cfg: Cfg, walk: Walk, edge: Edge) -> bool:
    """A RETURN edge belongs to one call site.

    Taking another call site's return joins that site's guard onto this path, and a
    paragraph performed from a dozen places would turn every guard set into the union
    of all of them. The legitimate targets are the FLOW successors of the node on top
    of the stack, because that is what build.py attached the return edges to.
    """
    if edge.kind is not EdgeKind.RETURN:
        return True
    return bool(walk.stack) and edge.target in _continuations(cfg, walk.stack[-1].call)


def _duplicates_a_return(cfg: Cfg, walk: Walk, edge: Edge) -> bool:
    """Whether this FLOW edge out of a CALL node goes where the paragraph's RETURN will.

    A CALL node keeps a FLOW edge to the statement after it AND a PERFORM edge into the
    paragraph, and the paragraph's RETURN edge lands on that same FLOW target. Walking
    both reaches everything after the call twice under one guard, and ten calls in a row
    would report 2^10 duplicate paths. So FLOW out of a CALL node is refused wherever
    this path takes the PERFORM instead.

    That refusal is a PREDICTION -- "the activation the PERFORM opens will run the
    paragraph to its end and the RETURN will land here" -- and predictions can be wrong.
    The two the graph can rule out up front are checked here: the path may be barred from
    entering at all by the recursion guard, and the paragraph may be unable to reach its
    own end at all, so the RETURN hanging off it can never fire for anyone
    (``_can_return``). What neither can rule out is the cap silently falsifying the
    prediction, which is what ``_resumed_to_fixpoint`` exists to repair.
    """
    return (
        edge.kind is EdgeKind.FLOW
        and _performs(cfg, walk, walk.node)
        and _can_return(cfg, edge)
    )


def _not_a_fallthrough_a_return_will_take(
    cfg: Cfg, walk: Walk, edge: Edge, seen: frozenset[str]
) -> bool:
    """A performed paragraph returns at its end; it does not fall through to the next.

    So a FALLTHRU edge is refused where the frame on top of the stack can still return
    from here. It is kept where the frame cannot -- a paragraph in the middle of a
    PERFORM A THRU B range reaches the next one by falling through, and control arriving
    with no frame at all falls through as written.

    Refusing that FALLTHRU is not cosmetic. Measured on a synthetic 922-node program of
    one driver paragraph performing forty others, following it left 39 nodes with no
    guards at all: the fall-through paths filled the cap and evicted the returns the
    driver's later statements are only reachable by. Over-approximating is the safe
    direction only while the cap is not the thing rationing the answer.
    """
    if edge.kind is not EdgeKind.FALLTHRU:
        return True
    return not _returns_from(cfg, walk)


def _continuations(cfg: Cfg, call_id: str) -> frozenset[str]:
    return frozenset(
        edge.target for edge in cfg.successors(call_id) if edge.kind is EdgeKind.FLOW
    )


def _performs(cfg: Cfg, walk: Walk, node_id: str) -> bool:
    """Whether this node has a PERFORM edge this path may follow.

    What bars a PERFORM is the stack, not the activation: a paragraph performed twice
    from the same caller runs twice, so ``seen`` has no say here.
    """
    return any(
        edge.kind is EdgeKind.PERFORM and _not_already_active(walk, edge)
        for edge in cfg.successors(node_id)
    )


def _not_already_active(walk: Walk, edge: Edge) -> bool:
    """The recursion guard: a paragraph may not be performed from inside itself.

    This is what bounds the stack, and it is also what COBOL says -- the standard
    leaves a PERFORM of an already-active paragraph undefined. Without it, ``PERFORM A``
    inside A would push frames until the interpreter ran out of them.
    """
    if edge.kind is not EdgeKind.PERFORM:
        return True
    return edge.target not in tuple(frame.target for frame in walk.stack)


def _can_return(cfg: Cfg, edge: Edge) -> bool:
    """Whether any RETURN onto this edge's target can ever fire.

    A graph-level dead-end test, and only that. A node with no in-edges at all is a
    node nothing in the graph reaches, so a performed paragraph whose only statement is
    a GO TO never arrives at its own end, and the return hanging off that end can never
    fire for anyone. Nothing here is path-sensitive: under the frame model a path that
    enters a paragraph walks it in a fresh activation and reaches the end unless the
    graph itself stops it, so the question of whether THIS path can still get to the
    return no longer arises. Asking it was the defect -- the answer was graph-level
    while the blockage was path-level, and the FLOW edge it refused was the only way
    past the call.
    """
    return any(
        bool(cfg.predecessors(back.source))
        for back in cfg.predecessors(edge.target)
        if back.kind is EdgeKind.RETURN
    )


def _returns_from(cfg: Cfg, walk: Walk) -> bool:
    """Whether the frame on top of the stack can return from this node.

    The frame's own ``seen`` is what the continuations are measured against, not the
    current activation's: the continuation is a statement in the CALLER, and whether
    the caller has already walked it is the caller's business.
    """
    if not walk.stack:
        return False
    frame = walk.stack[-1]
    continuations = _continuations(cfg, frame.call) - frame.seen
    return any(
        edge.kind is EdgeKind.RETURN and edge.target in continuations
        for edge in cfg.successors(walk.node)
    )


def _advance(walk: Walk, edge: Edge, seen: frozenset[str]) -> Walk:
    """The walk after taking this edge, with the activation opened or closed.

    A PERFORM opens one: the caller's ``seen`` goes into the frame and the callee
    starts with an empty one, which is what lets a paragraph run once per activation
    rather than once per path. A RETURN closes it and restores what the caller had
    walked, discarding the callee's -- the returning node belongs to the activation
    being left, not to the caller it lands in.
    """
    if edge.kind is EdgeKind.PERFORM:
        return Walk(
            node=edge.target,
            guard=_extended(walk, edge),
            stack=(
                *walk.stack,
                _Frame(call=edge.source, target=edge.target, seen=seen),
            ),
        )
    if edge.kind is EdgeKind.RETURN and walk.stack:
        return Walk(
            node=edge.target,
            guard=_extended(walk, edge),
            stack=walk.stack[:-1],
            seen=walk.stack[-1].seen,
        )
    return Walk(
        node=edge.target,
        guard=_extended(walk, edge),
        stack=walk.stack,
        seen=seen,
    )


def _extended(walk: Walk, edge: Edge) -> Guard:
    if edge.kind in POLARITIES:
        return (*walk.guard, (edge.source, edge.kind))
    return walk.guard


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
    """A gen/kill fixpoint using a worklist algorithm.

    The previous full-sweep approach recomputed all nodes every iteration,
    causing quadratic cost on large CFGs as frozensets grew. The worklist
    only reprocesses nodes whose predecessor OUT sets changed, giving
    O(edges × depth) cost in practice instead of O(nodes × iterations²).
    """
    generated = definitions_of(cfg)
    in_sets: dict[str, Defs] = {node.id: frozenset() for node in cfg.nodes}
    out_sets: dict[str, Defs] = {
        node.id: generated.get(node.id, frozenset())
        for node in cfg.nodes
    }
    worklist: set[str] = set(cfg.node_ids)
    processed = 0
    while worklist:
        node_id = worklist.pop()
        processed += 1
        new_in = frozenset(
            chain.from_iterable(
                out_sets[edge.source]
                for edge in cfg.predecessors(node_id)
            )
        )
        written = {d.field for d in generated.get(node_id, frozenset())}
        new_out = (
            frozenset(d for d in new_in if d.field not in written)
            | generated.get(node_id, frozenset())
        )
        if new_out != out_sets[node_id]:
            in_sets[node_id] = new_in
            out_sets[node_id] = new_out
            for edge in cfg.successors(node_id):
                worklist.add(edge.target)
    _log.info(
        "reaching_defs: %s  done  processed=%d",
        cfg.program, processed,
    )
    return in_sets


def _out_of(
    node_id: str, incoming: Mapping[str, Defs], generated: Mapping[str, Defs]
) -> Defs:
    """Gen/kill: definitions reaching this node, minus what it kills, plus what it generates."""
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


def condition_operands(atom: Atom) -> tuple[str, ...]:
    """The fields one guard step examines, and only the fields.

    ``atom.right`` is a second operand for a relation between two things and a VALUE
    for everything else -- a class name for IS NUMERIC, an 88's list of values for IN,
    the keyword RAISED for the handler test. Harvesting those reports ``NUMERIC`` and
    ``RAISED`` as fields the member never wrote, which spends the credibility of that
    line where it is genuinely true, as it is for a commarea or a file-read source.

    A synthetic left-hand side is the same case reached differently: the right of
    ``%HANDLER[ANY] RAISED`` or ``%IOSTATUS[F] == AT END`` is the state being tested
    for, not a field. The left IS kept -- whatever the test guards does depend on it --
    and the caller then labels it rather than claiming the member never wrote it.
    """
    if atom.op in VALUE_OPS or is_synthetic(atom.left):
        return (atom.left,)
    return (atom.left, atom.right)


def readers_of(cfg: Cfg, field: str) -> tuple[str, ...]:
    """Every node that reads this field, in source order.

    The mirror of ``writers_of``, and it has to look in two places to be one. An
    ASSIGN records its read operands in ``node.reads``, but a TEST holds the field it
    examines in its atom -- so a field that only ever decides a branch reads as unused
    when ``node.reads`` is the whole search, which is the opposite of true. Base-name
    matched, like ``writers_of``: a read of ``WS-TAB(1)`` answers a query for ``WS-TAB``.
    """
    base = base_field(field)
    return tuple(node.id for node in cfg.nodes if base in _read_bases(node))


def _read_bases(node: Node) -> frozenset[str]:
    examined = condition_operands(node.atom) if node.kind is NodeKind.TEST else ()
    return frozenset(base_field(name) for name in (*node.reads, *examined) if name)


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
