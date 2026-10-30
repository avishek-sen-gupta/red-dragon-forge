"""Intra-program worklist over CFG node entry states.

The ujr spike measured loop fixpoints as cheap -- 11,826 loops settled in one
iteration, 1,599 in two, the 30-iteration cap never reached. The cost was
recursive PERFORM inlining re-analysing a paragraph once per call path, which
took 710.58s on the corpus's worst member.

A PERFORM is not followed as an edge, though. Its range is walked from the
calling statement's state and only what reaches the range's end goes back, to
that statement's own resume: following the RETURN edges from a shared end would
hand one caller's writes to every other caller. What keeps this from becoming the
inlining above is reuse. A range's walk sees only the entries for bytes the range
can read or write (``perform_ranges``) and is keyed on those and on the open
PERFORMs the range could itself run into, so calls that bring the same entries
share one walk whatever path brought them there. The states a range's walks
settle on are joined into the program's per-node states for extraction.

Joining at the node is also what keeps a branch honest. Replaying a paragraph's
statements in declaration order would let an ELSE arm's write kill the THEN arm's
definition, and a dropped edge is invisible in the output -- exactly the failure
the lattice's may_alias/must_cover asymmetry exists to avoid.

The pass has two phases because they answer different questions. The fixpoint
settles what reaches each node; extraction then reads each statement's writes
once, at that settled state. Deriving edges by diffing the state around a
statement instead would lose every loop-carried flow -- the definition is already
in the in-state on the second visit, so the diff comes back empty.

What the settled state contributes is the defining node. A write stores, under
the target extent, the node that wrote it; so a later read of that extent
recovers where its value was last defined. That relation comes out as its own
stream -- keyed by (node, extent), one row per read -- rather than on the edges,
because a source extent commonly has several reaching definers and putting them
on the edge made one edge per definer, all stating the same flow. A read nothing
reaches is credited to the node reading it: an uninitialised read is still a read.

Termination does not rest on the cap: every extent a transfer can construct is
fixed by the statement set before iteration begins, so the lattice has finite
height and join is monotone. What the cap does defend against is cost, not
non-termination -- height lives in the per-extent source set, so the number of
growth events is nodes x extents x distinct sources, and a large member can want
hundreds of thousands of dequeues. A walk stopped there is published unsettled,
not dropped: by monotonicity its state is a subset of the fixpoint, so every flow
read off it is real.

The sweep walk is the cheap alternative. It visits in reverse postorder, where
every predecessor a node is reached through -- back edges aside -- is already
processed, so one sweep carries a forward chain of any length. A budget of
sweeps is an under-approximation with a name: a state still growing when the
budget runs out yields a subset of the true flows, never an invented one, and
``settled`` says which happened. Two sweeps is the interesting floor, because one
sweep loses everything a loop body wrote to every reader after the loop -- the
exit hangs off the loop's test node, whose own state arrives through the back
edge.

The coverage counters are rebuilt from the source, not from the answer. The 3ao
post-mortem found an acceptance suite passing while its walk reached 18% of
nodes, because the denominator was derived from what the walk had produced.
``writes`` counts write operands the statements name; ``covered`` counts those
whose extents resolved.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import reduce
from itertools import accumulate, pairwise, repeat, takewhile
from types import MappingProxyType

from cobble.dataflow.depgraph.flows import IDENTITY_PREFIXES
from cobble.dataflow.fields.extent import CellIndex, cell_index, operand_extents
from cobble.dataflow.fields.file_read import FileRead
from cobble.dataflow.fields.image import initial_image
from cobble.dataflow.fields.program_layout import NO_LAYOUT, ProgramLayout, layout_of
from cobble.dataflow.fields.origin import Origin
from cobble.dataflow.fields.sink import Sink
from cobble.dataflow.fields.sink_site import SinkSite
from cobble.dataflow.fields.sinks import sinks_of
from cobble.dataflow.fields.state import (
    EMPTY,
    Source,
    State,
    join,
    pruned,
    reaching,
    values_at,
)
from cobble.dataflow.fields.transfer import (
    HANDLED,
    REBUILT,
    Statement,
    Write,
    transfer,
    write_operands,
    writes_of,
)
from cobble.dataflow.fields.unmodelled_write import UnmodelledWrite
from cobble.dataflow.fields.values import EMPTY as VALUES_EMPTY
from cobble.dataflow.fields.values import ValueSet
from cobble.dataflow.fixpoint.fallthrough import fallthroughs_pruned
from cobble.dataflow.fixpoint.perform_ranges import (
    NO_RANGES,
    PerformRanges,
    Split,
    perform_ranges,
    restored,
    split,
)
from cobble.dataflow.fixpoint.live import EVERYTHING, Live
from cobble.dataflow.fixpoint.options import DEFAULT_OPTIONS, AnalysisOptions
from cobble.dataflow.fixpoint.stepped import Stepped
from cobble.dataflow.fixpoint.targets import ResolvedTarget, resolved_targets
from cobble.dataflow.jumps.discover import jumps_of
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.layout import UnsizeableFieldError, program_records
from cobble.dataflow.srccfg.build import label_id, paragraph_order
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, Node
from cobble.dataflow.srccfg.conditions import EightyEight, condition_index
from cobble.dataflow.srccfg.literals import is_literal
from cobble.dataflow.srccfg.order import DepthFirstOrder, depth_first_order
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.statements import statement_index
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_statements import ReadStatement
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId

logger = logging.getLogger(__name__)

HEARTBEAT = 2000

NO_INDEX = cell_index(())
NO_STATES: Mapping[str, State] = MappingProxyType({})


@dataclass(frozen=True)
class FlowEdge:
    """One value reaching one extent at one statement.

    ``origin`` names a value that is not storage -- a literal, a file, a callee --
    and is ``NO_ORIGIN`` exactly when ``source`` is a real range.

    Where the value was last defined is deliberately absent. One source extent at
    one node can have many reaching definers, so carrying the definer here made
    each of those one edge per definer; ``ReachingDef`` holds the relation instead,
    keyed by the pair this edge already names.

    ``landing`` is where the source's first byte lands, as an offset into the
    target, when the statement moves the bytes unchanged; nothing when it rewrites
    them or their place is not known. ``rebuilt`` says the statement built the
    target's value in place (arithmetic, STRING), not copied bytes into it from elsewhere.
    """

    origin: Origin
    source: FieldExtent
    target: FieldExtent
    node: str
    landing: tuple[int, ...] = ()
    rebuilt: bool = False


@dataclass(frozen=True)
class FlowSink:
    """Bytes leaving the program at one statement -- a record written, a map sent,
    a queue written -- and the statements that last wrote them there."""

    node: str
    sink: Sink
    source: FieldExtent
    definers: tuple[str, ...]


@dataclass(frozen=True)
class ReachingDef:
    """Which statements could have written ``extent`` by the time ``node`` runs."""

    node: str
    extent: FieldExtent
    definers: tuple[str, ...]
    held: ValueSet = VALUES_EMPTY


@dataclass(frozen=True)
class _Extracted:
    """Both streams one pass over the statements produces.

    One pass rather than two, because ``writes_of`` is where the transfer
    functions run and the edges and the definitions read the same writes.
    """

    edges: tuple[FlowEdge, ...] = ()
    defs: tuple[ReachingDef, ...] = ()


@dataclass(frozen=True)
class ProgramFlow:
    """Every field-level flow in one program, with what the pass did not reach.

    ``skipped`` non-empty means the numbers describe an abandoned analysis and
    must not be counted towards a coverage floor.

    ``settled`` False means the walk ran out of budget while the state was still
    growing: the edges are a subset of the program's flows, and ``back_edges``
    is how much cyclic structure it had left to resolve. Unlike ``skipped``, the
    edges are still worth reading -- nothing here is invented, only missing.
    """

    program: str
    edges: tuple[FlowEdge, ...] = ()
    defs: tuple[ReachingDef, ...] = ()
    sinks: tuple[FlowSink, ...] = ()
    targets: tuple[ResolvedTarget, ...] = ()
    jumps: tuple[Jump, ...] = ()
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    unmodelled: int = 0
    nodes: int = 0
    dequeues: int = 0
    sweeps: int = 0
    back_edges: int = 0
    settled: bool = True
    skipped: str = ""
    tracked: int = 0
    relevant: int = 0


@dataclass(frozen=True)
class _Tally:
    """What the statements ask for, counted before any of them is analysed."""

    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    unmodelled: int = 0


@dataclass(frozen=True)
class _Progress:
    """The previous heartbeat's reading, which is what an estimate needs.

    A worklist has nothing that counts down, so there is no progress to read off
    one sample. What it does have is a queue that drains: two samples give a
    rate, and the rate against the cap answers the question actually being asked
    of a run that has been going for twenty minutes.
    """

    started: float = 0.0
    dequeues: int = 0
    queued: int = 0


@dataclass(frozen=True)
class _Scope:
    """The PERFORM range a walk runs inside: the end it returns from, the range
    entries already active above it, which a PERFORM may not re-enter, and what the
    program's ranges can touch and reach."""

    closing: str = ""
    active: frozenset[str] = frozenset()
    ranges: PerformRanges = NO_RANGES


TOP = _Scope()


@dataclass(frozen=True)
class _RangeCall:
    """One PERFORM range entered from one exact state, with the ranges active above
    it -- everything a walk of the range depends on, so equal calls walk alike."""

    entry: str
    closing: str
    active: frozenset[str]
    sources: frozenset[tuple[FieldExtent, frozenset[Source]]]
    values: frozenset[tuple[FieldExtent, ValueSet]]
    unwritten: frozenset[tuple[RegionId, tuple[int, ...]]]


def _range_call(entry: str, scope: _Scope, state: State) -> _RangeCall:
    return _RangeCall(
        entry=entry,
        closing=scope.closing,
        active=scope.active,
        sources=frozenset(state.sources.items()),
        values=frozenset(state.values.items()),
        unwritten=frozenset(state.unwritten.items()),
    )


@dataclass(frozen=True)
class _Returned:
    """What one walk of a range gave: the state leaving the range's end, keyed by
    that end and absent when the walk never got there, and the state the walk
    settled on each node inside the range. Nothing here names a call site, so it
    serves every call that enters the range from the same state."""

    leaving: Mapping[str, State]
    inner: Mapping[str, State]


@dataclass(frozen=True)
class _Site:
    """One PERFORM statement entering its range under one set of active ranges."""

    call: str
    entry: str
    closing: str
    active: frozenset[str]


@dataclass(frozen=True)
class _Settled:
    """The last walk of a range from one site: the state it entered with, and the
    states it settled on the range's nodes and on the ranges it called."""

    entered: State = EMPTY
    states: Mapping[str, State] = NO_STATES
    inner: Mapping[str, State] = NO_STATES


NOT_WALKED = _Settled()


@dataclass(frozen=True)
class _Known:
    """Range walks done so far: each result by the exact call it answers, and each
    site's latest walk, which a later walk from a larger state resumes."""

    results: Mapping[_RangeCall, _Returned] = MappingProxyType({})
    walks: Mapping[_Site, _Settled] = MappingProxyType({})


NO_CALLS = _Known()


@dataclass(frozen=True)
class _Worklist:
    """One step of the worklist: entry states settled so far, and what to revisit.

    ``queue`` holds reverse-postorder positions, not node ids: each step takes the
    earliest, so a node is revisited only after the nodes that feed it have had
    their turn -- the same fixpoint as any order, reached in far fewer dequeues.
    """

    states: Mapping[str, State]
    queue: frozenset[int]
    dequeues: int = 0
    progress: _Progress = _Progress()
    cursor: int = 0
    inner: Mapping[str, State] = NO_STATES
    calls: _Known = NO_CALLS


@dataclass(frozen=True)
class _Outflow:
    """What leaving one node sends on: entry states for its successors, every
    state the PERFORM ranges it called settled on their own nodes, and the range
    walks known so far."""

    flows: Mapping[str, State]
    inner: Mapping[str, State] = NO_STATES
    dequeues: int = 0
    calls: _Known = NO_CALLS


@dataclass(frozen=True)
class _Walk:
    """What a traversal produced, whichever traversal ran.

    The two walks answer to different budgets -- dequeues against a cap, sweeps
    against a count -- so what they have in common is the settled states, how
    much work it took, and whether the answer is complete.
    """

    states: Mapping[str, State] = NO_STATES
    dequeues: int = 0
    sweeps: int = 0
    back_edges: int = 0
    settled: bool = True
    skipped: str = ""


def _statements_at(
    cfg: Cfg, statements: Mapping[str, Statement]
) -> tuple[tuple[str, Statement], ...]:
    return tuple(
        (node.id, statements[node.id]) for node in cfg.nodes if node.id in statements
    )


def program_statements(asg: CobolASG, cfg: Cfg) -> Mapping[str, Statement]:
    """The statement at every CFG node, as the transfer reads them."""
    return with_unmodelled(
        with_record_areas(statement_index(asg), asg.file_record_to_select),
        cfg,
        condition_index(asg),
    )


def with_record_areas(
    statements: Mapping[str, Statement], file_of_record: Mapping[str, str]
) -> Mapping[str, Statement]:
    """Every READ as the fields it fills: its file's 01 records, which share the
    record area, and its INTO field."""
    return MappingProxyType(
        {
            node_id: _file_read(statement, file_of_record)
            for node_id, statement in statements.items()
        }
    )


def _file_read(statement: Statement, file_of_record: Mapping[str, str]) -> Statement:
    if not isinstance(statement, ReadStatement):
        return statement
    into = (statement.into,) if statement.into.name else ()
    records = tuple(
        RefModOperand(name=record)
        for record, owner in file_of_record.items()
        if owner == statement.file_name.upper()
    )
    return FileRead(file_name=statement.file_name, targets=into + records)


def with_unmodelled(
    statements: Mapping[str, Statement],
    cfg: Cfg,
    eighty_eights: Mapping[str, EightyEight],
) -> Mapping[str, Statement]:
    """Every statement the transfer has no handler for, but that lowering says
    writes storage, replaced by the weak write it is read as.

    The names come from the CFG node, which already holds what every statement
    kind writes and reads. A level-88 name stands for its parent field, which is
    the storage a ``SET ... TO TRUE`` changes.
    """
    return MappingProxyType(
        {
            node_id: _unmodelled_or(statement, node_id, cfg, eighty_eights)
            for node_id, statement in statements.items()
        }
    )


def _unmodelled_or(
    statement: Statement,
    node_id: str,
    cfg: Cfg,
    eighty_eights: Mapping[str, EightyEight],
) -> Statement:
    if isinstance(statement, HANDLED) or node_id not in cfg.node_ids:
        return statement
    node = cfg.node(node_id)
    targets = _storage(node.writes, eighty_eights)
    if not targets:
        return statement
    return UnmodelledWrite(
        verb=node.transfer or type(statement).__name__,
        targets=targets,
        sources=_storage(node.reads, eighty_eights),
    )


def _storage(
    names: Sequence[str], eighty_eights: Mapping[str, EightyEight]
) -> tuple[RefModOperand, ...]:
    return tuple(
        RefModOperand(name=_parent(name, eighty_eights))
        for name in dict.fromkeys(names)
        if name and not is_literal(name) and not name.startswith(IDENTITY_PREFIXES)
    )


def _parent(name: str, eighty_eights: Mapping[str, EightyEight]) -> str:
    condition = eighty_eights.get(name.upper())
    return condition.parent if condition else name


def _resolved(operands: Sequence[RefModOperand], index: CellIndex) -> int:
    return sum(1 for operand in operands if operand_extents(operand, index).extents)


def _one_tally(statement: Statement, index: CellIndex) -> _Tally:
    """An unmodelled write has no handler and still writes: it counts as both."""
    if isinstance(statement, UnmodelledWrite):
        operands = statement.targets
        return _Tally(
            writes=len(operands),
            covered=_resolved(operands, index),
            unhandled=1,
            unmodelled=len(operands),
        )
    if not isinstance(statement, HANDLED):
        return _Tally(unhandled=1)
    operands = write_operands(statement)
    return _Tally(writes=len(operands), covered=_resolved(operands, index))


def _target_operands(statement: Statement) -> tuple[RefModOperand, ...]:
    if isinstance(statement, UnmodelledWrite):
        return tuple(statement.targets)
    if not isinstance(statement, HANDLED):
        return ()
    return tuple(write_operands(statement))


def _warn_untracked(
    program: str, found: tuple[tuple[str, Statement], ...], index: CellIndex
) -> None:
    missing = tuple(
        (node_id, operand.name)
        for node_id, statement in found
        for operand in _target_operands(statement)
        if operand_extents(operand, index).reason == "unknown-name"
    )
    for node_id, name in missing:
        logger.warning(
            "fields: %s %s writes %s, which has no memory definition;"
            " the write is not tracked",
            program,
            node_id,
            name,
        )


def _tally(found: tuple[tuple[str, Statement], ...], index: CellIndex) -> _Tally:
    counted = tuple(_one_tally(statement, index) for _, statement in found)
    return _Tally(
        writes=sum(one.writes for one in counted),
        covered=sum(one.covered for one in counted),
        unhandled=sum(one.unhandled for one in counted),
        unmodelled=sum(one.unmodelled for one in counted),
    )


def _entry_node(asg) -> str:
    order = paragraph_order(asg)
    return label_id(order[0].name) if order else ""


def _after(
    statements: Mapping[str, Statement],
    node_id: str,
    before: State,
    index: CellIndex,
) -> State:
    statement = statements.get(node_id)
    if not statement:
        return before
    return transfer(statement, node_id, before, index)


def _arriving(states: Mapping[str, State], target: str, after: State) -> State:
    """What reaches ``target`` once ``after`` does: the first path to arrive is all
    there is, and a later one joins it. ``EMPTY`` is not a stand-in for "no path
    yet" -- it is a path that wrote nothing, and joining with it would add doubt
    about every value the arriving path holds."""
    if target in states:
        return join(states[target], after)
    return after


def _grown(
    flows: Mapping[str, State], states: Mapping[str, State]
) -> Mapping[str, State]:
    """Successors whose entry state the flows leaving a node enlarge."""
    joined = {
        target: _arriving(states, target, state) for target, state in flows.items()
    }
    return {
        target: state
        for target, state in joined.items()
        if state != states.get(target, EMPTY) or target not in states
    }


def _outflow(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    cap: int,
    scope: _Scope,
    node_id: str,
    after: State,
    known: _Known,
) -> _Outflow:
    """Where the state leaving ``node_id`` goes, with every PERFORM matched to its
    own call site.

    The end of the range being walked sends nothing on: the caller reads it as the
    range's exit. A RETURN edge is never followed, because it leads to every call
    site of the range at once. A PERFORM is not followed either: the range is
    walked from this call's state, and only what reaches its end goes to this
    call's resume.
    """
    if node_id == scope.closing:
        return _Outflow(flows=NO_STATES, calls=known)
    edges = cfg.successors(node_id)
    plain = _Outflow(
        flows={
            edge.target: _for(after, live, edge.target)
            for edge in edges
            if edge.kind not in (EdgeKind.PERFORM, EdgeKind.RETURN)
        },
        calls=known,
    )
    node = cfg.node(node_id)
    return reduce(
        lambda out, entry: _with_call(
            out,
            _called(cfg, statements, index, live, cap, scope, node, entry, after, out),
        ),
        tuple(
            edge.target
            for edge in edges
            if edge.kind is EdgeKind.PERFORM and edge.target not in scope.active
        ),
        plain,
    )


def _called(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    cap: int,
    scope: _Scope,
    call: Node,
    entry: str,
    after: State,
    sofar: _Outflow,
) -> _Outflow:
    """The range this call enters, walked from this call's state -- or, when an
    equal call was already walked, what that walk gave.

    A walk from a state that contains the one this site last entered with picks
    up where that walk stopped: its settled states are the fixpoint for a smaller
    entry, so they lie below this walk's and the worklist only has to carry the
    growth. A site whose new state does not contain the old one -- the same
    statement reached in a walk of its range entered from another caller -- walks
    afresh, so one caller's state never seeds another's.
    """
    inside = _Scope(
        closing=call.range_end, active=scope.active | {entry}, ranges=scope.ranges
    )
    parts = split(after, scope.ranges.footprint(entry, call.range_end))
    entered = parts.inside
    relevant = inside.active & scope.ranges.reaches(entry, call.range_end)
    key = _range_call(entry, _Scope(closing=inside.closing, active=relevant), entered)
    if key in sofar.calls.results:
        hit = sofar.calls.results[key]
        return _Outflow(
            flows=_resumed(live, call, hit, parts),
            inner=_restored_all(hit.inner, parts),
            calls=sofar.calls,
        )
    site = _Site(
        call=call.id, entry=entry, closing=inside.closing, active=inside.active
    )
    earlier = sofar.calls.walks.get(site, NOT_WALKED)
    resumed = earlier if join(earlier.entered, entered) == entered else NOT_WALKED
    run = _settled(
        cfg, statements, index, live, entry, cap, entered, inside, sofar.calls, resumed
    )
    returned = _Returned(
        leaving=_leaving(statements, index, call.range_end, run.states),
        inner=_merged(run.inner, run.states),
    )
    return _Outflow(
        flows=_resumed(live, call, returned, parts),
        inner=_restored_all(returned.inner, parts),
        dequeues=run.dequeues,
        calls=_Known(
            results=MappingProxyType({**run.calls.results, key: returned}),
            walks=MappingProxyType(
                {
                    **run.calls.walks,
                    site: _Settled(entered=entered, states=run.states, inner=run.inner),
                }
            ),
        ),
    )


def _leaving(
    statements: Mapping[str, Statement],
    index: CellIndex,
    closing: str,
    states: Mapping[str, State],
) -> Mapping[str, State]:
    if closing not in states:
        return NO_STATES
    return {closing: _after(statements, closing, states[closing], index)}


def _resumed(
    live: Live, call: Node, returned: _Returned, parts: Split
) -> Mapping[str, State]:
    if call.range_end not in returned.leaving or not call.resume:
        return NO_STATES
    leaving = restored(returned.leaving[call.range_end], parts.outside)
    return {call.resume: _for(leaving, live, call.resume)}


def _restored_all(inner: Mapping[str, State], parts: Split) -> Mapping[str, State]:
    return MappingProxyType(
        {node: restored(state, parts.outside) for node, state in inner.items()}
    )


def _with_call(left: _Outflow, right: _Outflow) -> _Outflow:
    return _Outflow(
        flows=_merged(left.flows, right.flows),
        inner=_merged(left.inner, right.inner),
        dequeues=left.dequeues + right.dequeues,
        calls=right.calls,
    )


def _merged(
    left: Mapping[str, State], right: Mapping[str, State]
) -> Mapping[str, State]:
    if not right:
        return left
    return MappingProxyType(
        {
            **left,
            **{
                node: join(left[node], state) if node in left else state
                for node, state in right.items()
            },
        }
    )


def _for(state: State, live: Live, node: str) -> State:
    if live.everything:
        return state
    return pruned(state, lambda extent: live.keeps(node, extent))


def _eta(run: _Worklist, cap: int) -> str:
    """What the drain rate says is left, or why it says nothing yet.

    Two readings of the queue give dequeues per node drained, and the elapsed
    time gives dequeues per second. Neither is a promise: a worklist can tail off
    once few nodes remain re-enqueueable, or stall. The part worth acting on is
    the comparison against the cap, because that decides whether waiting is worth
    anything or the factor needs raising.
    """
    if not run.progress.dequeues:
        return "no rate yet"
    drained = run.progress.queued - len(run.queue)
    spent = run.dequeues - run.progress.dequeues
    elapsed = time.monotonic() - run.progress.started
    if drained <= 0 or spent <= 0 or elapsed <= 0:
        return "queue not draining"
    left = len(run.queue) * spent / drained
    if run.dequeues + left > cap:
        return f"~{left:,.0f} dequeues left, past the {cap} cap"
    return f"~{left * elapsed / run.dequeues / 60:.0f}m left, ~{left:,.0f} dequeues"


def _heartbeat(cfg: Cfg, run: _Worklist, cap: int) -> None:
    """A pass that runs for minutes has to say so while it runs.

    Reach against the node count is the number worth watching: a walk that stops
    growing it is churning state over a fraction of the program (the 3ao failure),
    and one that never stops is heading for the cap.
    """
    logger.info(
        "fields:   %s %d dequeues, %d/%d nodes reached, %d queued, %s",
        cfg.program,
        run.dequeues,
        len(run.states),
        len(cfg.nodes),
        len(run.queue),
        _eta(run, cap),
    )


def _step(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    cap: int,
    order: DepthFirstOrder,
    rank: Mapping[str, int],
    run: _Worklist,
    scope: _Scope = TOP,
) -> _Worklist:
    earliest = _next(run.queue, run.cursor)
    node_id = order.ordered[earliest]
    after = _after(statements, node_id, run.states[node_id], index)
    out = _outflow(cfg, statements, index, live, cap, scope, node_id, after, run.calls)
    grown = _grown(out.flows, run.states)
    stepped = _Worklist(
        states=MappingProxyType({**run.states, **grown}),
        queue=(run.queue - {earliest}) | {rank[target] for target in grown},
        dequeues=run.dequeues + 1 + out.dequeues,
        progress=run.progress,
        cursor=earliest + 1,
        inner=_merged(run.inner, out.inner),
        calls=out.calls,
    )
    if stepped.dequeues % HEARTBEAT:
        return stepped
    _heartbeat(cfg, stepped, cap)
    return replace(
        stepped,
        progress=replace(
            stepped.progress, dequeues=stepped.dequeues, queued=len(stepped.queue)
        ),
    )


def _next(queue: frozenset[int], cursor: int) -> int:
    """The first queued position at or after ``cursor``, wrapping to the earliest.

    Round-robin over reverse postorder rather than always the earliest: a change
    that flows back around a loop waits for the pass in progress to reach the end,
    so writers found further on are carried back together in one pass instead of
    each restarting the walk at the loop head.
    """
    ahead = tuple(position for position in queue if position >= cursor)
    return min(ahead) if ahead else min(queue)


def _done(run: _Worklist, cap: int) -> bool:
    return not run.queue or run.dequeues >= cap


def _settled(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    entry: str,
    cap: int,
    entry_state: State,
    scope: _Scope = TOP,
    calls: _Known = NO_CALLS,
    resumed: _Settled = NOT_WALKED,
) -> _Worklist:
    """Iterate to a fixpoint, or to the cap if a defect keeps the state growing.

    ``accumulate`` over an endless source is lazy, so no step runs past the one
    that settles -- and ``next`` needs no default because ``dequeues`` rises by one
    per step while the queue is non-empty, so the predicate holds within ``cap``
    whether or not the fixpoint was found. Which of the two happened is read back
    off ``queue``.
    """
    order = depth_first_order(cfg, entry)
    rank = MappingProxyType({node_id: n for n, node_id in enumerate(order.ordered)})
    start = _Worklist(
        states=_merged(resumed.states, {entry: entry_state}),
        queue=frozenset({rank[entry]}),
        progress=_Progress(started=time.monotonic()),
        inner=resumed.inner,
        calls=calls,
    )
    passes = accumulate(
        repeat(None),
        lambda run, _: _step(
            cfg, statements, index, live, cap, order, rank, run, scope
        ),
        initial=start,
    )
    return next(run for run in passes if _done(run, cap))


def _sweep_progress(cfg: Cfg, sweep: int, visited: int, total: int) -> None:
    """A sweep knows its denominator, which the worklist never does.

    Reverse postorder fixes the node count before the pass starts, so progress is
    a fraction of a known whole rather than a queue length with nothing to compare
    it against -- no estimate needed, and none of the drain-rate arithmetic the
    worklist's heartbeat has to do to say anything at all.
    """
    logger.info(
        "fields:   %s sweep %d, %d/%d nodes visited (%.0f%%)",
        cfg.program,
        sweep,
        visited,
        total,
        100.0 * visited / total,
    )


def _sweep_done(
    cfg: Cfg, sweep: int, budget: int, states: Mapping[str, State], settled: bool
) -> None:
    logger.info(
        "fields:   %s sweep %d of %d done, %d nodes reached, %s",
        cfg.program,
        sweep,
        budget,
        len(states),
        "settled" if settled else "still growing",
    )


def _propagated(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    order: DepthFirstOrder,
    states: Mapping[str, State],
    sweep: int,
) -> Mapping[str, State]:
    """One reverse-postorder sweep, pushing each node's exit state to successors.

    Back edges need no special case. Their source sits later in the order, so on
    the first sweep it has nothing to contribute yet and on every later sweep it
    contributes what the previous sweep left there -- which is how a second sweep
    recovers the flow out of a loop that a single sweep cannot see.
    """
    grown = dict(states)
    for visited, node_id in enumerate(order.ordered, start=1):
        after = _after(statements, node_id, grown[node_id], index)
        for edge in cfg.successors(node_id):
            grown[edge.target] = _arriving(
                grown, edge.target, _for(after, live, edge.target)
            )
        if not visited % HEARTBEAT:
            _sweep_progress(cfg, sweep, visited, len(order.ordered))
    return MappingProxyType(grown)


def _swept(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    entry: str,
    budget: int,
    entry_state: State,
) -> _Walk:
    """Sweep until nothing grows or the budget is spent, whichever comes first.

    A sweep that changes nothing means the fixpoint was reached, and the answer
    is as exact as the worklist's would have been for a fraction of the work. A
    spent budget means an under-approximation: join and the transfer are
    monotone, so a smaller entry state yields fewer sources and never a wrong
    one, and every def-use pair reported is real.

    With no back edge there is nothing to confirm: reverse postorder gives every
    node its whole entry state on the first sweep, so one sweep is the fixpoint
    and a second would only prove it at the cost of another pass. With back
    edges it takes the sweep that changes nothing, which is why a budget of one
    can never report a settled loop even when it found every flow in it.
    """
    order = depth_first_order(cfg, entry)
    states: Mapping[str, State] = MappingProxyType({entry: entry_state})
    sweep, settled = 0, False
    while sweep < budget and not settled:
        grown = _propagated(cfg, statements, index, live, order, states, sweep + 1)
        sweep, settled = sweep + 1, grown == states or not order.back_edges
        states = grown
        _sweep_done(cfg, sweep, budget, states, settled)
    return _Walk(
        states=states,
        dequeues=sweep * len(order.ordered),
        sweeps=sweep,
        back_edges=len(order.back_edges),
        settled=settled,
    )


def _worked(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    entry: str,
    factor: int,
    entry_state: State,
) -> _Walk:
    cap = factor * max(len(cfg.nodes), 1)
    top = _Scope(ranges=perform_ranges(cfg, statements, index))
    run = _settled(cfg, statements, index, live, entry, cap, entry_state, top)
    _warn_if_capped(run, cap, cfg.program, len(cfg.nodes))
    return _Walk(
        states=_merged(run.inner, run.states),
        dequeues=run.dequeues,
        settled=not run.queue,
    )


def _walked(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    live: Live,
    entry: str,
    options: AnalysisOptions,
    entry_state: State,
) -> _Walk:
    """An entry the CFG does not hold reaches nothing, and is not a failure.

    A program whose first paragraph never became a node has no walk to run; the
    coverage counters still come from the statements, so the member is reported
    as uncovered rather than as skipped.
    """
    if entry not in cfg.node_ids:
        return _Walk()
    if options.sweeps:
        return _swept(cfg, statements, index, live, entry, options.sweeps, entry_state)
    return _worked(cfg, statements, index, live, entry, options.factor, entry_state)


def _definers(state: State, extent: FieldExtent) -> frozenset[str]:
    """Where the value at ``extent`` was last written; nothing when no statement in
    the program wrote it, and its content is its VALUE clause or nothing at all."""
    return frozenset(source.node for source in reaching(state, extent))


def _landing(write: Write, source: Source) -> tuple[int, ...]:
    if not source.origin.is_storage or not write.copy_start:
        return ()
    return (source.extent.start - write.copy_start[0],)


def _at(
    statement: Statement,
    node_id: str,
    state: State,
    index: CellIndex,
    kept: Callable[[str, FieldExtent], bool],
) -> _Extracted:
    """One statement's flows and the definitions reaching what it read.

    A synthetic source contributes no definition row: the value came from outside
    storage, so the statement holding it is the only statement that could have
    produced it, and ``node`` already names that one.
    """
    moved = tuple(
        (write, source)
        for write in writes_of(statement, node_id, index)
        if kept(node_id, write.target)
        for source in write.sources
    )
    return _Extracted(
        edges=tuple(
            FlowEdge(
                origin=source.origin,
                source=source.extent,
                target=write.target,
                node=node_id,
                landing=_landing(write, source),
                rebuilt=isinstance(statement, REBUILT),
            )
            for write, source in moved
        ),
        defs=tuple(
            ReachingDef(
                node=node_id,
                extent=source.extent,
                definers=tuple(sorted(_definers(state, source.extent))),
                held=values_at(state, source.extent),
            )
            for _, source in moved
            if source.origin.is_storage
        ),
    )


def _extracted(
    found: tuple[tuple[str, Statement], ...],
    states: Mapping[str, State],
    index: CellIndex,
    kept: Callable[[str, FieldExtent], bool],
) -> _Extracted:
    """Every statement the CFG can reach, read once at its settled entry state.

    Statement order outside, sorted within each statement. The sources at an
    extent are a frozenset and the definers of one source are another, so the
    order ``_at`` yields varies with the per-process hash seed: two runs of the
    same walk over the same member would emit the same facts in a different
    order, and an artefact that differs between identical runs cannot be diffed
    across a corpus, which is how a regression in this pipeline gets caught.
    Sorting the whole stream instead would fix that too, at the cost of the source
    order a reader compares against the listing.
    """
    parts = tuple(
        _at(statement, node_id, states[node_id], index, kept)
        for node_id, statement in found
        if node_id in states
    )
    return _Extracted(
        edges=tuple(
            dict.fromkeys(
                edge for part in parts for edge in sorted(part.edges, key=repr)
            )
        ),
        defs=tuple(
            dict.fromkeys(
                entry for part in parts for entry in sorted(part.defs, key=repr)
            )
        ),
    )


def _warn_if_capped(run: _Worklist, cap: int, program: str, nodes: int) -> None:
    """A walk stopped at the cap is published unsettled, as a sweep budget's is:
    the state so far is a subset of the fixpoint, so its flows are real and only
    some may be missing."""
    if not run.queue:
        return
    logger.warning(
        "fields: dequeue cap %d reached for %s (%d nodes); publishing unsettled",
        cap,
        program,
        nodes,
    )


def analyse(
    asg,
    index: CellIndex,
    options: AnalysisOptions = DEFAULT_OPTIONS,
    entry_state: State = EMPTY,
) -> ProgramFlow:
    """Every flow in one program, given an index its fields can be laid out into.

    ``options.factor`` is dequeues allowed per CFG node before the worklist walk
    gives up. No constant is right for every program: the bound is nodes times
    the lattice height at each node, and the height is the distinct sources held
    at each extent. ``options.sweeps`` runs the cheaper walk instead, whose
    budget is passes over the program rather than visits to a node.

    ``entry_state`` is what reaches the program before any statement runs -- the
    initial image of WORKING-STORAGE's VALUE clauses, when the caller has one.
    """
    unpruned = program_cfg(asg)
    statements = program_statements(asg, unpruned)
    cfg = fallthroughs_pruned(unpruned, paragraph_order(asg), statements)
    found = _statements_at(cfg, statements)
    _warn_untracked(cfg.program, found, index)
    tally = _tally(found, index)
    live = EVERYTHING
    entry = _entry_node(asg)
    walk = _walked(
        cfg, statements, index, live, entry, options, _for(entry_state, live, entry)
    )
    kept = _kept_after(cfg, live)
    extracted = _extracted(found, walk.states, index, kept)
    written = _written(found, index)
    return ProgramFlow(
        program=cfg.program,
        edges=extracted.edges,
        defs=extracted.defs,
        sinks=_sunk(
            found, walk.states, index, MappingProxyType(asg.file_record_to_select)
        ),
        targets=resolved_targets(cfg, index, walk.states, walk.settled),
        jumps=jumps_of(asg, cfg, statements, index, walk.states, walk.settled, live),
        writes=tally.writes,
        covered=tally.covered,
        unhandled=tally.unhandled,
        unmodelled=tally.unmodelled,
        nodes=len(cfg.nodes),
        dequeues=walk.dequeues,
        sweeps=walk.sweeps,
        back_edges=walk.back_edges,
        settled=walk.settled,
        skipped=walk.skipped,
        tracked=len({write.target for _, write in written}),
        relevant=len(
            {write.target for node, write in written if kept(node, write.target)}
        ),
    )


def _sinks_at(statement: Statement, files: Mapping[str, str]) -> tuple[SinkSite, ...]:
    """A WRITE of a record no SELECT names has no file to name, so it is no sink."""
    try:
        return sinks_of(statement, files)
    except KeyError:
        return ()


def _sunk(
    found: tuple[tuple[str, Statement], ...],
    states: Mapping[str, State],
    index: CellIndex,
    files: Mapping[str, str],
) -> tuple[FlowSink, ...]:
    """Each sink's bytes, with the definers the statement itself leaves on them."""
    return tuple(
        dict.fromkeys(
            FlowSink(
                node=node_id,
                sink=sink.sink,
                source=extent,
                definers=tuple(sorted(_definers(after, extent))),
            )
            for node_id, statement in found
            if node_id in states
            for sinks in (_sinks_at(statement, files),)
            if sinks
            for after in (transfer(statement, node_id, states[node_id], index),)
            for sink in sinks
            for extent in operand_extents(sink.operand, index).extents
        )
    )


def _written(
    found: tuple[tuple[str, Statement], ...], index: CellIndex
) -> tuple[tuple[str, Write], ...]:
    return tuple(
        (node_id, write)
        for node_id, statement in found
        for write in writes_of(statement, node_id, index)
    )


def _kept_after(cfg: Cfg, live: Live) -> Callable[[str, FieldExtent], bool]:
    if live.everything:
        return lambda node, extent: True
    return lambda node, extent: any(
        live.keeps(edge.target, extent) for edge in cfg.successors(node)
    )


def program_graph(asg) -> tuple[Cfg, Mapping[str, Statement]]:
    """The pruned CFG a walk runs over, and the statements at its nodes."""
    unpruned = program_cfg(asg)
    statements = program_statements(asg, unpruned)
    return fallthroughs_pruned(unpruned, paragraph_order(asg), statements), statements


def entry_of(asg) -> str:
    return _entry_node(asg)


def stepwise(asg, options: AnalysisOptions, cap: int) -> tuple[Cfg, Iterator[Stepped]]:
    """The worklist walk ``analysed`` runs, one step at a time, for a diagnostic.

    Laid out and seeded exactly as ``analysed`` does it, and stopped after ``cap``
    dequeues or when the queue empties.
    """
    built = _laid_out(asg, NO_LAYOUT)
    unpruned = program_cfg(asg)
    statements = program_statements(asg, unpruned)
    cfg = fallthroughs_pruned(unpruned, paragraph_order(asg), statements)
    live = EVERYTHING
    entry = _entry_node(asg)
    if entry not in cfg.node_ids:
        return cfg, iter(())
    order = depth_first_order(cfg, entry)
    rank = MappingProxyType({node_id: n for n, node_id in enumerate(order.ordered)})
    top = _Scope(ranges=perform_ranges(cfg, statements, built.index))
    start = _Worklist(
        states=MappingProxyType(
            {
                entry: _for(
                    State(values=initial_image(built.records, built.index)),
                    live,
                    entry,
                )
            }
        ),
        queue=frozenset({rank[entry]}),
        progress=_Progress(started=time.monotonic()),
    )

    def advanced(run: _Worklist, _: None) -> _Worklist:
        if _done(run, cap):
            return run
        return _step(cfg, statements, built.index, live, cap, order, rank, run, top)

    runs = accumulate(repeat(None), advanced, initial=start)
    return cfg, (
        Stepped(
            node=order.ordered[_next(before.queue, before.cursor)],
            before=before.states,
            after=after.states,
            queued=len(after.queue),
            dequeues=after.dequeues,
        )
        for before, after in takewhile(
            lambda pair: not _done(pair[0], cap), pairwise(runs)
        )
    )


def _laid_out(asg, layout: ProgramLayout) -> ProgramLayout:
    """The layout the caller already had, or this program's own.

    ``NO_LAYOUT`` is the absence, not an empty program: a program really declaring
    nothing has records of its own and never compares equal to the sentinel by
    identity.
    """
    if layout is NO_LAYOUT:
        return layout_of(program_records(asg))
    return layout


def analysed(
    asg,
    options: AnalysisOptions = DEFAULT_OPTIONS,
    layout: ProgramLayout = NO_LAYOUT,
) -> tuple[ProgramFlow, CellIndex]:
    """analyse, with the layout built here so an unsizeable field is a skip.

    layout raises while computing extents, which is before any statement has been
    seen, so a program that cannot be laid out has no partial answer worth
    returning -- only a recorded reason. Never silently dropped. The index that
    comes back with a skip is ``NO_INDEX``, which holds no cells.

    ``layout`` is for a caller that already has the records -- read back from the
    extents table rather than laid out again. Given one, nothing here touches the
    DATA DIVISION, and an unsizeable field was the other caller's to report.
    """
    try:
        built = _laid_out(asg, layout)
    except UnsizeableFieldError as error:
        return ProgramFlow(program=asg.program_id, skipped=str(error)), NO_INDEX
    entry_state = State(values=initial_image(built.records, built.index))
    return analyse(asg, built.index, options, entry_state), built.index
