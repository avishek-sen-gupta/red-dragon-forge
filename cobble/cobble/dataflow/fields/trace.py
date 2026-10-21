"""One concrete path at a time, with a real byte store and no join anywhere.

The fixpoint next door answers "could these bytes flow" over every path at once,
which costs it two things a path gets for free. A PERFORMed paragraph returns to
every caller, because ``srccfg/build.py`` lowers it once and gives it one RETURN
edge per site; on a path the stack says which site is yours. And a call is a
wall, because ``transfer`` credits a commarea to ``%CALL:<name>`` and knows
nothing of the callee; on a path a LINK is a step into the callee, and the
write-back needs no mechanism at all -- in a byte-addressable model the two sides
are the same storage.

What it gives up is soundness in the other direction. Every dependency here was
witnessed by an actual path, and absence means "not sampled", never "does not
exist". The two walks answer different questions and this one replaces nothing.

The store is keyed by program OUTSIDE the extent, because ``RegionId`` is an enum
of six DATA DIVISION sections and carries no program: two members'
``WORKING_STORAGE@100`` are the same ``FieldExtent``, and ``may_alias`` would
conflate them. Slicing by program keeps every may_alias/must_cover comparison
inside one program's storage, where those predicates are sound, and needs no
change to ``cobol_memory``, which is vendored.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache, reduce
from itertools import repeat
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.aliases import NO_EXTENT, UNSIZEABLE, commarea_aliases
from cobble.dataflow.fields.extent import CellIndex, cell_index, operand_extents
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.sinks import sinks_of
from cobble.dataflow.fields.state import (
    EMPTY,
    NOWHERE,
    Source,
    State,
    reaching,
    write,
)
from cobble.dataflow.fields.transfer import Statement, Write, writes_of
from cobble.dataflow.layout import UnsizeableFieldError, program_records
from cobble.dataflow.srccfg.build import (
    label_id,
    paragraph_order,
)
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, NodeKind
from cobble.dataflow.srccfg.desugar import CALL_TRANSFER, LINK_TRANSFER, XCTL_TRANSFER
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.statements import statement_index
from cobble.parsing.asg_cache import first_program_at
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

logger = logging.getLogger(__name__)

DEFAULT_PATHS = 200
DEFAULT_COVERAGE = 1.0
DEFAULT_MAX_DEPTH = 50000

CROSSING_VERBS = (LINK_TRANSFER, XCTL_TRANSFER, CALL_TRANSFER)

NO_PROCEDURE = "callee-has-no-procedure"
NOT_PARSED = "callee-not-parsed"
OUTSIDE_SINGLE_PROGRAM = "outside-single-program"
RE_ENTRY = "re-entry"


@dataclass(frozen=True)
class Budget:
    """When to stop sampling, and how long one path may be.

    ``max_depth`` is a cost bound, not a correctness one: the re-entry rule
    already makes every path finite, but a program with thousands of paragraphs
    reachable in sequence can still make one path long enough to be useless.
    """

    paths: int = DEFAULT_PATHS
    coverage: float = DEFAULT_COVERAGE
    max_depth: int = DEFAULT_MAX_DEPTH


DEFAULT_BUDGET = Budget()


@dataclass(frozen=True)
class Window:
    """Shared storage's two ends -- a commarea, or one CALL argument -- the
    caller's bytes and the callee's, same length.

    ``known`` False is a call site with no window to bind -- a dynamic target, a
    callee absent from the cache, an operand naming no field. A sentinel rather
    than an absent value, so a caller compares windows the same way everywhere.
    ``writes_back`` is whether the callee's writes reach the caller: a LINK's
    commarea and a BY REFERENCE argument do; an XCTL's commarea and a BY CONTENT or
    BY VALUE argument, a copy, do not.
    """

    caller: str = ""
    caller_extent: FieldExtent = NO_EXTENT
    callee_extent: FieldExtent = NO_EXTENT
    known: bool = False
    writes_back: bool = False


NO_WINDOW = Window()


@dataclass(frozen=True)
class Dep:
    """One statement's write, one source of it, and where that source was defined.

    ``origin`` is non-empty exactly when the source is not storage, and
    ``definers`` is then empty -- nothing in any program wrote a literal or a file
    record. ``definers`` are program-qualified node ids, which is what lets a
    definer that crossed a call name the member it is in. ``via`` is the call site
    this program was entered through, innermost when nested, and empty in the
    program the trace started from.

    ``program`` addresses ``target``; ``source_program`` addresses ``source``. They
    differ only at a LINK return, where the caller's window is credited to bytes
    that are still named in the callee's own address space -- and an extent is only
    comparable to another in the same program, so collapsing the two would both
    hide the callee's writes and let the caller's bytes at those offsets stand in
    for them.
    """

    program: str
    node: str
    target: FieldExtent
    origin: str
    source: FieldExtent
    definers: tuple[str, ...]
    via: str
    source_program: str
    sink: str = ""


@dataclass(frozen=True)
class DeadEnd:
    """A call site a sampled path arrived at and could not cross.

    Its own stream rather than a field on ``Dep``, because there is no write to
    hang it on: the path did not enter the callee, so nothing was witnessed there.
    """

    program: str
    node: str
    transfer: str
    callee: str
    reason: str


@dataclass(frozen=True)
class Coverage:
    """Branch edges taken, against every branch edge in the programs entered.

    The denominator comes from the ``Cfg``s, never from what the walk produced:
    the 3ao post-mortem found an acceptance suite passing while its walk reached
    18% of nodes, because the denominator was derived from the answer.
    """

    taken: frozenset[tuple[str, str, str]] = frozenset()
    total: int = 0
    programs: frozenset[str] = frozenset()

    @property
    def fraction(self) -> float:
        """One, not zero, for a program with no branches: there is nothing left to
        sample, so a target of 1.0 is met rather than unreachable."""
        return len(self.taken) / self.total if self.total else 1.0


@dataclass(frozen=True)
class Trace:
    """Everything the sampled paths witnessed, deduplicated.

    No path ids. The report is the union over paths, and an id would only label a
    route the report does not print.
    """

    deps: frozenset[Dep] = frozenset()
    dead_ends: frozenset[DeadEnd] = frozenset()
    paths: int = 0
    coverage: Coverage = Coverage()


def _extent_at(text: str) -> FieldExtent:
    """The artefact's wire form back to an extent, or a length of nothing.

    ``FieldExtent.__str__`` spells the region as ``RegionId``'s own value, so the
    enum constructor is the way back and there is no mapping to keep in step.
    """
    found = byte_range(text, "")
    if not found.known:
        return NO_EXTENT
    return FieldExtent(
        region=RegionId(found.region),
        start=found.start,
        length=found.length,
        precision=Precision.EXACT if found.exact else Precision.CLAMPED,
        field_name=found.name,
    )


def _window(row: CommareaAlias, callee: str) -> Window:
    """The two ends of one site's shared storage, or NO_WINDOW.

    A zero-length end is not a narrow window, it is no window: overlap needs
    ``start < other.end``, so nothing can ever be bound through ``[n:n]``.
    """
    caller = _extent_at(row.caller_extent)
    landed = _extent_at(row.callee_extent)
    if not caller.length or not landed.length:
        return NO_WINDOW
    return Window(
        caller=row.caller,
        caller_extent=caller,
        callee_extent=landed,
        known=True,
        writes_back=row.returns,
    )


def _rebased(
    extent: FieldExtent, source: FieldExtent, target: FieldExtent
) -> FieldExtent:
    """``extent``'s overlap with ``source``, at the same offset inside ``target``.

    Clipped to the window, because the bytes outside it are not shared storage and
    a rebase that kept them would claim the callee addresses the caller's whole
    record. Named for ``target``: spelling the caller's field name inside the
    callee's region names a field that is not declared there.
    """
    start = max(extent.start, source.start)
    end = min(extent.end, source.end, source.start + target.length)
    return replace(
        extent,
        region=target.region,
        start=target.start + start - source.start,
        length=end - start,
        field_name=target.field_name,
    )


def _seeded(held: State, source: FieldExtent, target: FieldExtent) -> State:
    """Every extent overlapping ``source``, rebased onto ``target``, provenance kept.

    A binding, not a flow: caller byte ``source.start + k`` *is* callee byte
    ``target.start + k``, so the sources carry across unchanged and no node is
    credited with a write.

    Unioned by rebased extent rather than built as a comprehension over it, because
    two distinct extents can clip to the same shared range -- a record and a
    redefinition of it -- and a comprehension keyed on the result would drop one of
    them silently.
    """
    bound = tuple(
        (_rebased(extent, source, target), sources)
        for extent, sources in held.sources.items()
        if extent.may_alias(source)
    )
    rebased_extents = tuple({extent: None for extent, _ in bound})
    return State(
        sources=MappingProxyType(
            {
                rebased_extent: frozenset(
                    one
                    for extent, sources in bound
                    if extent == rebased_extent
                    for one in sources
                )
                for rebased_extent in rebased_extents
            }
        )
    )


NO_CFG = Cfg(program="", nodes=(), edges=())
NO_INDEX = cell_index(())
NO_STATEMENTS: Mapping[str, Statement] = MappingProxyType({})
NO_FILES: Mapping[str, str] = MappingProxyType({})
NO_ALIASES: Mapping[str, tuple[CommareaAlias, ...]] = MappingProxyType({})
NO_STORE: Mapping[str, State] = MappingProxyType({})


@dataclass(frozen=True)
class Loaded:
    """One program's compiled artefacts, or the reason it cannot be entered.

    Built once per program per process and reused across every path, because a
    parse and a layout cost far more than a walk over them.
    """

    program: str
    cfg: Cfg = NO_CFG
    statements: Mapping[str, Statement] = NO_STATEMENTS
    index: CellIndex = NO_INDEX
    entry: str = ""
    aliases: Mapping[str, tuple[CommareaAlias, ...]] = NO_ALIASES
    files: Mapping[str, str] = NO_FILES
    reason: str = ""


Loader = Callable[[str], Loaded]


LOOP_ITERATIONS = 2


@dataclass(frozen=True)
class Frame:
    """One open invocation: where it resumes, and how many times each node has run.

    Popped whole on return, which is what makes the re-entry rule right in all
    three of its cases. A paragraph's visited nodes leave with its frame, so a
    second PERFORM of the same paragraph starts clean; a frame still open still
    forbids re-entry, which covers a loop's back edge, a recursive PERFORM and a
    LINK cycle with one rule. The count allows a configurable number of loop
    iterations before the re-entry rule fires.
    """

    program: str
    site: str = ""
    resume: str = ""
    crossing: bool = False
    returns: bool = False
    caller: str = ""
    windows: tuple[Window, ...] = ()
    visits: MappingProxyType[str, int] = MappingProxyType({})


@dataclass(frozen=True)
class _Choice:
    """One decision a path made: the arm it took, and each arm's branch-coverage key.

    The arms are recorded rather than looked up again -- the same node under a
    different stack can offer a different set. Their count says whether an untried arm
    is left, and their keys say which branch edge flipping to the next one would take,
    which is what lets a queued plan be ordered before it runs. A decision at a node
    coverage does not count carries empty keys.
    """

    taken: int
    arms: tuple[frozenset[tuple[str, str, str]], ...]


@dataclass(frozen=True)
class _Checkpoint:
    """The walk state at a multi-arm decision: its node has run, no arm is taken yet.

    Holds only what is needed to resume: the execution state (node, stack, store,
    program) and the decisions made so far.  ``order`` carries the node sequence
    accumulated before the checkpoint so that a resumed walk can present a complete
    path to a ``PathListener`` rather than only the suffix from the flip point.
    """

    node: str
    stack: tuple[Frame, ...]
    store: Mapping[str, State]
    made: tuple[_Choice, ...]
    entered: frozenset[str]
    order: tuple[str, ...] = ()


def _via(stack: tuple[Frame, ...]) -> str:
    """The call site the program on top of ``stack`` was entered through.

    A function of the stack rather than of the walk, because a dep is not always
    attributed to the frame the walk is standing in: a bridge row belongs to the
    caller and is built while the callee's frame is still on the stack, so it asks
    for the via of the stack it is about, not the one the walk is on.
    """
    crossings = tuple(one for one in stack if one.crossing)
    if not crossings:
        return ""
    return f"{crossings[-1].caller}/{crossings[-1].site}"


@dataclass(frozen=True)
class _Walk:
    """One path, mid-flight. Threaded, never mutated.

    A path is its ``plan``: the arm index to take at each decision, in the order the
    decisions arise. The walk is a pure function of it, so a plan names a route
    exactly and replaying one is not sampling but reproduction. Past the plan's end
    the first arm is taken, and ``made`` records what every decision actually did --
    which is where the next plans come from.
    """

    node: str
    stack: tuple[Frame, ...]
    store: Mapping[str, State] = NO_STORE
    plan: tuple[int, ...] = ()
    made: tuple[_Choice, ...] = ()
    deps: frozenset[Dep] = frozenset()
    dead_ends: frozenset[DeadEnd] = frozenset()
    taken: frozenset[tuple[str, str, str]] = frozenset()
    entered: frozenset[str] = frozenset()
    order: tuple[str, ...] = ()
    running: bool = True
    checkpoints: tuple[_Checkpoint, ...] = ()

    @property
    def frame(self) -> Frame:
        """The innermost open invocation. The stack is never empty while running:
        the root of a path is a frame like any other."""
        return self.stack[-1]

    @property
    def program(self) -> str:
        return self.frame.program

    @property
    def via(self) -> str:
        """The call site this program was entered through, innermost when nested."""
        return _via(self.stack)


@dataclass(frozen=True)
class _Next:
    """A queued walk: either a plan from the entry (base route) or a checkpoint
    to resume from with a flipped arm.

    ``branch`` is the branch edge the flip will take, known before the walk runs,
    which is what lets the queue order by what it would buy.
    """

    plan: tuple[int, ...] = ()
    branch: frozenset[tuple[str, str, str]] = frozenset()
    checkpoint: _Checkpoint = _Checkpoint(
        node="", stack=(), store=NO_STORE, made=(), entered=frozenset()
    )
    arm: int = 0
    from_checkpoint: bool = False


@dataclass(frozen=True)
class _Queue:
    """The plans not yet walked, in three lanes, each taken from the front.

    ``fresh`` holds the plans whose own flip takes a branch edge nothing has taken and
    no other queued plan already promises to take. ``uncounted`` holds the plans whose
    flip is at a decision coverage does not count -- a CICS command's raise arm -- so
    there is no branch edge to judge them by and only walking one says what it reaches.
    ``stale`` holds the rest. The lanes drain in that order, and the run stops once
    only ``stale`` is left; an empty queue means every route the re-entry rule admits
    was walked exactly once.

    The lanes exist because insertion order is enormously redundant against coverage:
    93083 plans pending on a real member flipped only 475 distinct branch edges, 202 of
    them already taken, so path after path re-covered an arm some earlier path had
    covered and the fraction froze between path 500 and path 2000. Within a lane the
    order is still front-first, so a plan flipping a shallow decision runs before one
    flipping a deep one; a stack instead of a queue would be plain depth-first search,
    which permutes the tail of one route for thousands of paths before it revisits the
    entry's own branch.

    It starts holding the empty plan -- the route where every decision takes its first
    arm.
    """

    fresh: tuple[_Next, ...] = (_Next(),)
    uncounted: tuple[_Next, ...] = ()
    stale: tuple[_Next, ...] = ()
    promised: frozenset[tuple[str, str, str]] = frozenset()


@dataclass(frozen=True)
class _Run:
    """The sampler's accumulator: the trace so far, and the plans not yet walked.

    ``stopped`` is why sampling ended when the budget and the coverage target were not
    the reason, carried out rather than re-derived by the reporter.
    """

    trace: Trace = Trace()
    queue: _Queue = _Queue()
    stopped: str = ""


def _empty(queue: _Queue) -> bool:
    return not queue.fresh and not queue.uncounted and not queue.stale


def _head(queue: _Queue) -> _Next:
    """The next plan to walk. Only meaningful on a queue that is not empty."""
    if queue.fresh:
        return queue.fresh[0]
    return queue.uncounted[0] if queue.uncounted else queue.stale[0]


def _drained(queue: _Queue) -> _Queue:
    if queue.fresh:
        return replace(queue, fresh=queue.fresh[1:])
    if queue.uncounted:
        return replace(queue, uncounted=queue.uncounted[1:])
    return replace(queue, stale=queue.stale[1:])


def _filed(queue: _Queue, taken: frozenset[tuple[str, str, str]], one: _Next) -> _Queue:
    """One generated plan into the lane its flip earns."""
    if not one.branch:
        return replace(queue, uncounted=(*queue.uncounted, one))
    if not one.branch <= (taken | queue.promised):
        return replace(
            queue,
            fresh=(*queue.fresh, one),
            promised=queue.promised | one.branch,
        )
    return replace(queue, stale=(*queue.stale, one))


def _extended(
    queue: _Queue, taken: frozenset[tuple[str, str, str]], nexts: Sequence[_Next]
) -> _Queue:
    """The queue with one path's alternatives filed into their lanes.

    The batch is sorted on its own and spliced once. Filing straight into the queue
    would copy a hundred-thousand-entry tuple per generated plan, and a path generates
    hundreds.
    """
    batch = reduce(
        lambda held, one: _filed(held, taken, one),
        nexts,
        _Queue(fresh=(), promised=queue.promised),
    )
    return _Queue(
        fresh=(*queue.fresh, *batch.fresh),
        uncounted=(*queue.uncounted, *batch.uncounted),
        stale=(*queue.stale, *batch.stale),
        promised=batch.promised,
    )


def _max_visits(node: str) -> int:
    """Loop headers (containing #loop) are allowed LOOP_ITERATIONS visits; everything else once."""
    return LOOP_ITERATIONS if "#loop" in node else 1


def _open(stack: Sequence[Frame], program: str, node: str) -> bool:
    """The re-entry rule: an edge back to a node an open frame has run too many times."""
    return any(
        one.program == program and one.visits.get(node, 0) >= _max_visits(node)
        for one in stack
    )


def _marked(stack: tuple[Frame, ...], node: str) -> tuple[Frame, ...]:
    frame = stack[-1]
    count = frame.visits.get(node, 0) + 1
    return (
        *stack[:-1],
        replace(frame, visits=MappingProxyType({**frame.visits, node: count})),
    )


def _qualified(writes: Sequence[Write], program: str) -> tuple[Write, ...]:
    """``state.Source`` carries a bare node id, and a definer that crossed a call
    is in another member -- so every id going into the store is program-qualified.
    """
    return tuple(
        replace(
            entry,
            sources=frozenset(
                replace(one, node=f"{program}/{one.node}") for one in entry.sources
            ),
        )
        for entry in writes
    )


def _writes(walk: _Walk, loaded: Loaded) -> tuple[Write, ...]:
    """Whatever this node's statement writes, or nothing where there is no statement.

    Membership rather than a ``get`` that may come back empty-handed: a LABEL or a
    NOP has no statement at all, which is not the same fact as a statement that
    writes nothing.
    """
    if walk.node not in loaded.statements:
        return ()
    return _qualified(
        writes_of(loaded.statements[walk.node], walk.node, loaded.index), walk.program
    )


def _definers(held: State, source: Source) -> tuple[str, ...]:
    """Where the source's bytes were last written on this path.

    Empty for a synthetic origin: nothing in any program wrote a literal or a file
    record, and naming a definer for one would invent a flow.
    """
    if source.origin:
        return ()
    return _reached(held, source.extent)


def _reached(held: State, extent: FieldExtent) -> tuple[str, ...]:
    return tuple(sorted({one.node for one in reaching(held, extent)}))


def _witnessed(walk: _Walk, held: State, writes: Sequence[Write]) -> frozenset[Dep]:
    """One dependency per (target, source) pair, definers read out of the slice as
    it stood BEFORE the statement.

    ``reaching`` here is the whole reason the store exists. ``writes_of`` builds a
    ``Source`` from the source operand's own extents and never consults the state,
    so without this read the walk would only restate the statement it just ran.
    """
    return frozenset(
        Dep(
            program=walk.program,
            node=walk.node,
            target=entry.target,
            origin=one.origin,
            source=one.extent,
            definers=_definers(held, one),
            via=walk.via,
            source_program=walk.program,
        )
        for entry in writes
        for one in entry.sources
    )


def _sunk(walk: _Walk, held: State, loaded: Loaded) -> frozenset[Dep]:
    """One dep per extent a statement sends out, read after its own writes, so
    ``WRITE rec FROM x`` names its own move into the record area."""
    if walk.node not in loaded.statements:
        return frozenset()
    return frozenset(
        Dep(
            program=walk.program,
            node=walk.node,
            target=NOWHERE,
            origin="",
            source=extent,
            definers=_reached(held, extent),
            via=walk.via,
            source_program=walk.program,
            sink=sink.name,
        )
        for sink in sinks_of(loaded.statements[walk.node], loaded.files)
        for extent in operand_extents(sink.operand, loaded.index).extents
    )


def _applied(held: State, writes: Sequence[Write]) -> State:
    return reduce(
        lambda state, entry: write(state, entry.target, entry.sources), writes, held
    )


def _ran(walk: _Walk, loaded: Loaded, bound: tuple[Window, ...] = ()) -> _Walk:
    """This node's statement against this program's slice, and what it witnessed.

    ``bound`` is the windows of a callee about to be entered. The statement's own
    transfer credits them to ``%CALL:<callee>``, which is what a call nobody steps
    into must say; one that is stepped into shares those bytes instead, so its
    writes there are left to the callee.
    """
    held = walk.store.get(walk.program, EMPTY)
    writes = tuple(
        entry
        for entry in _writes(walk, loaded)
        if not any(entry.target.may_alias(one.caller_extent) for one in bound)
    )
    after = _applied(held, writes)
    return replace(
        walk,
        stack=_marked(walk.stack, walk.node),
        store={**walk.store, walk.program: after},
        deps=walk.deps | _witnessed(walk, held, writes) | _sunk(walk, after, loaded),
        entered=walk.entered | {walk.program},
        order=(*walk.order, walk.node),
    )


def _sequel(cfg: Cfg, node: str) -> str:
    """Where a call or a PERFORM continues once it comes back.

    A PERFORM whose range resolved records it on the node, because its range always
    runs and ``build.py`` keeps no edge past it. A call continues along its own
    FLOW edge, as does a PERFORM of a range the program does not declare.
    """
    resume = cfg.node(node).resume
    if resume:
        return resume
    return next(
        (edge.target for edge in cfg.successors(node) if edge.kind is EdgeKind.FLOW),
        "",
    )


def _stepped_over(cfg: Cfg, node: str) -> tuple[Edge, ...]:
    """The way past a PERFORM the re-entry rule refused: to where it would have
    resumed, skipping the paragraphs it would have run again."""
    resume = cfg.node(node).resume
    if not resume:
        return ()
    return (Edge(source=node, target=resume, kind=EdgeKind.FLOW),)


def _return_edge(walk: _Walk, edges: Sequence[Edge]) -> tuple[Edge, ...]:
    """The one RETURN edge going back to the innermost frame's own resume point.

    The first path-insensitivity cost paid off: ``build.py`` gives a paragraph one
    RETURN edge per PERFORM site and the fixpoint takes them all, because only a
    stack knows which site is yours. A crossing frame is excluded because a RETURN
    edge belongs to a PERFORM, and matching one against a callee's resume point
    would be a node-id coincidence rather than a return.
    """
    if walk.frame.crossing:
        return ()
    return tuple(
        one
        for one in edges
        if one.kind is EdgeKind.RETURN and one.target == walk.frame.resume
    )[:1]


def _admissible(walk: _Walk, loaded: Loaded, edges: Sequence[Edge]) -> tuple[Edge, ...]:
    """Everything left once the stack has had its say, arms that go nowhere last.

    PERFORM edges are gone because a refused one means the paragraph is skipped and
    this node's own FLOW edge is the continuation. RETURN edges are gone because
    the path reached this node without performing it -- by falling through -- and
    its callers' resume points are none of its business.

    An arm whose target has no successors of its own ends the path there, and
    ``desugar._raisable`` makes such an arm the FIRST one at every CICS command with
    no NOHANDLE and no RESP: its raising arm is a ``#dispatch`` node, which has no
    exits wherever no HANDLE CONDITION is armed (``program_cfg`` joins it to the
    handlers that are). Since a
    plan continues with the first arm past its own end, leaving that arm first ends
    every route at the first such command beyond its last flip -- measured at 663 of
    9030 reachable nodes on a real member, whatever the path budget. The order is
    stable, so a plan recorded under it still replays exactly.
    """
    return tuple(
        sorted(
            (
                one
                for one in edges
                if one.kind is not EdgeKind.PERFORM
                and one.kind is not EdgeKind.RETURN
                and not _open(walk.stack, walk.program, one.target)
            ),
            key=lambda one: not loaded.cfg.successors(one.target),
        )
    )


def _branch(loaded: Loaded, node: str, edge: Edge) -> frozenset[tuple[str, str, str]]:
    """Coverage counts branch edges only.

    A TEST has exactly two out-edges and everything else has one route through it,
    so counting the rest would make the percentage a node count wearing a branch's
    name.
    """
    if loaded.cfg.node(node).kind is not NodeKind.TEST:
        return frozenset()
    return frozenset({(loaded.program, node, edge.kind.value)})


def _index(walk: _Walk) -> int:
    """Which arm to take at this decision: the plan's, or the first arm past its end.

    The plan is indexed by how many decisions this path has already made, not by node
    id, so replaying a plan is exact even where a node is visited under two different
    stacks with two different sets of admissible arms.
    """
    at = len(walk.made)
    return walk.plan[at] if at < len(walk.plan) else 0


def _checkpoint_of(walk: _Walk) -> _Checkpoint:
    return _Checkpoint(
        node=walk.node,
        stack=walk.stack,
        store=walk.store,
        made=walk.made,
        entered=walk.entered,
        order=walk.order,
    )


def _sampled(walk: _Walk, loaded: Loaded, edges: Sequence[Edge]) -> _Walk:
    """One step. A node with a single admissible arm is not a decision and is not
    recorded, so a plan stays as short as the choices it actually fixes."""
    if not edges:
        return _ended(walk)
    if len(edges) == 1:
        return _advanced(walk, loaded, edges[0], walk.made)
    index = _index(walk)
    saved = _checkpoint_of(walk)
    return _advanced(
        replace(walk, checkpoints=(*walk.checkpoints, saved)),
        loaded,
        edges[index],
        (
            *walk.made,
            _Choice(
                taken=index,
                arms=tuple(_branch(loaded, walk.node, one) for one in edges),
            ),
        ),
    )


def _advanced(
    walk: _Walk, loaded: Loaded, edge: Edge, made: tuple[_Choice, ...]
) -> _Walk:
    return replace(
        walk,
        node=edge.target,
        made=made,
        taken=walk.taken | _branch(loaded, walk.node, edge),
    )


def _alternatives(walk: _Walk, plan_len: int) -> tuple[_Next, ...]:
    """One alternative per untried arm, from the plan's own flip point onward.

    Each alternative carries the checkpoint at that decision, so resuming it
    starts from the exact walk state where the decision was made — no replay.
    Checkpoints are indexed from where the walk started making new decisions:
    on a fresh walk that is 0; on a resumed walk it is len(checkpoint.made),
    the prefix inherited from the checkpoint.
    """
    prefix = len(walk.made) - len(walk.checkpoints)
    return tuple(
        _Next(
            plan=(*(one.taken for one in walk.made[:at]), walk.made[at].taken + 1),
            branch=walk.made[at].arms[walk.made[at].taken + 1],
            checkpoint=walk.checkpoints[at - prefix],
            arm=walk.made[at].taken + 1,
            from_checkpoint=True,
        )
        for at in range(max(plan_len - 1, 0), len(walk.made))
        if walk.made[at].taken + 1 < len(walk.made[at].arms) and at >= prefix
    )


def _performed(walk: _Walk, loaded: Loaded, edge: Edge) -> _Walk:
    return replace(
        walk,
        node=edge.target,
        stack=(
            *walk.stack,
            Frame(
                program=walk.program,
                site=walk.node,
                resume=_sequel(loaded.cfg, walk.node),
            ),
        ),
    )


def _returned(walk: _Walk, edge: Edge) -> _Walk:
    """Pop the frame and continue at the resume point the edge just confirmed."""
    return replace(walk, node=edge.target, stack=walk.stack[:-1])


def _restored(caller: State, back: State) -> State:
    """The caller's slice with the shared window written back from the callee's.

    ``state.write`` rather than a union: the callee's write to those bytes really
    did kill what the caller held there, and ``must_cover`` is what says so. Not
    ``state.join``, which is the fixpoint's operation and is never called here.

    The callee's slice can hold overlapping extents -- a group and its elementary
    items both defined. Sequential ``write`` per extent has to pick an order, and
    widest-first is chosen so the narrow, specific definitions are the ones that
    survive ``must_cover``'s kills.
    """
    return reduce(
        lambda held, pair: write(held, pair[0], pair[1]),
        sorted(
            back.sources.items(),
            key=lambda pair: (
                pair[0].region.value,
                pair[0].start,
                -pair[0].length,
                pair[0].field_name,
            ),
        ),
        caller,
    )


def _bridge(
    frame: Frame,
    resumed: tuple[Frame, ...],
    store: Mapping[str, State],
    back: State,
) -> frozenset[Dep]:
    """Dep rows recording the byte transfer from callee back to caller.

    ``_restored`` seeds the caller's state from ``back`` but emits nothing,
    so backward provenance queries stop at ``%CALL:<callee>`` with no source
    to follow.  These rows close that gap: for every callee extent that flows
    back, one dep row per source maps the rebased caller extent to the original
    source extent, letting the query cross the LINK boundary.

    The row belongs to the caller, so it is addressed from the caller's stack --
    ``resumed``, the one the walk is about to stand on -- and not from the callee's
    frame, which is still on top while these rows are built. ``source`` is named in
    the address space of the program that read it, which is the callee only for
    bytes the callee wrote: bytes it never touched still carry the source they were
    seeded with. Naming the right program is what lets the query find the callee's
    own writes rather than the caller's bytes at the same offsets, and the reverse.
    """
    return frozenset(
        Dep(
            program=frame.caller,
            node=frame.site,
            target=caller_ext,
            origin=source.origin,
            source=source.extent,
            definers=_definers(store.get(_reader(source), EMPTY), source),
            via=_via(resumed),
            source_program=_reader(source),
        )
        for caller_ext, sources in back.sources.items()
        for source in sources
    )


def _reader(source: Source) -> str:
    """The program whose statement read ``source``: every node id in the store is
    program-qualified by ``_qualified``, and a PROGRAM-ID holds no slash."""
    return source.node.partition("/")[0]


def _unwound(stack: tuple[Frame, ...]) -> tuple[Frame, ...]:
    """The stack cut back to its innermost crossing frame, empty when it has none.

    A callee's path can end inside a PERFORMed paragraph, so the frame on top when
    the path runs out is not necessarily the frame that owes a caller its bytes.
    """
    crossings = tuple(index for index, frame in enumerate(stack) if frame.crossing)
    return stack[: crossings[-1] + 1] if crossings else ()


def _resumable(stack: tuple[Frame, ...]) -> tuple[Frame, ...]:
    """The stack cut back to the innermost PERFORM frame that has a resume point.

    Only frames above the innermost crossing one are candidates, so a crossing
    frame's owed write-back is never skipped over.
    """
    crossings = tuple(index for index, frame in enumerate(stack) if frame.crossing)
    floor = crossings[-1] + 1 if crossings else 0
    performs = tuple(
        index
        for index in range(floor, len(stack))
        if not stack[index].crossing and stack[index].resume
    )
    return stack[: performs[-1] + 1] if performs else ()


def _ended(walk: _Walk) -> _Walk:
    """Nowhere left to go, unless an open frame owes somewhere a return.

    A PERFORMed paragraph whose only exits the re-entry rule refuses is not the end
    of the path: its performer's resume point is right there on the stack, and no
    RETURN edge is needed to use it. Discarding the path instead loses every route
    past the performer -- measured at 487 of 500 path deaths on a real member.
    """
    resumable = _resumable(walk.stack)
    if resumable:
        return replace(walk, node=resumable[-1].resume, stack=resumable[:-1])
    return _handed_back(walk, _unwound(walk.stack))


def _handed_back(walk: _Walk, unwound: tuple[Frame, ...]) -> _Walk:
    """The path back in the caller that a crossing frame owes its bytes to.

    Seeding the caller's windows back needs no conversion and no flow edge: the
    two sides were the same bytes all along. Only a window that writes back is
    seeded -- a BY CONTENT argument was a copy. An empty resume point is a call
    that was the last thing its caller did, so there is nothing to come back to.
    """
    if not (unwound and unwound[-1].returns and unwound[-1].resume):
        return replace(walk, running=False)
    frame = unwound[-1]
    resumed = unwound[:-1]
    callee_state = walk.store.get(frame.program, EMPTY)
    return reduce(
        lambda back_walk, window: _window_back(
            back_walk, frame, resumed, callee_state, window
        ),
        (window for window in frame.windows if window.writes_back),
        replace(walk, node=frame.resume, stack=resumed),
    )


def _window_back(
    walk: _Walk,
    frame: Frame,
    resumed: tuple[Frame, ...],
    callee_state: State,
    window: Window,
) -> _Walk:
    back = _seeded(callee_state, window.callee_extent, window.caller_extent)
    return replace(
        walk,
        deps=walk.deps | _bridge(frame, resumed, walk.store, back),
        store={
            **walk.store,
            frame.caller: _restored(walk.store.get(frame.caller, EMPTY), back),
        },
    )


def _followed(walk: _Walk, loaded: Loaded) -> _Walk:
    """Along an edge. PERFORM and RETURN are decided by the stack; the rest sampled.

    A PERFORM edge is always taken rather than sampled: the range always runs. A
    refused PERFORM -- its target is on the stack -- passes over the paragraphs to
    where it would have resumed, rather than abandoning the path.
    """
    edges = loaded.cfg.successors(walk.node)
    performed = tuple(one for one in edges if one.kind is EdgeKind.PERFORM)
    if performed and not _open(walk.stack, walk.program, performed[0].target):
        return _performed(walk, loaded, performed[0])
    returned = _return_edge(walk, edges)
    if returned:
        return _returned(walk, returned[0])
    over = _stepped_over(loaded.cfg, walk.node) if performed else ()
    return _sampled(walk, loaded, (*_admissible(walk, loaded, edges), *over))


def _dead_end(walk: _Walk, row: CommareaAlias, reason: str) -> _Walk:
    return replace(
        walk,
        dead_ends=walk.dead_ends
        | {
            DeadEnd(
                program=walk.program,
                node=walk.node,
                transfer=row.transfer,
                callee=row.callee,
                reason=reason,
            )
        },
    )


def _entered(
    walk: _Walk,
    loaded: Loaded,
    row: CommareaAlias,
    windows: tuple[Window, ...],
    callee: Loaded,
) -> _Walk:
    """Step into the callee with its shared windows bound.

    The callee's slice starts empty because CICS gives a LINKed program fresh
    WORKING-STORAGE, so a program entered twice on one path does not inherit its
    own earlier run's memory; each window seeds it with the caller's bytes there.
    The resume point is read off the CALLER's graph: that is where the path comes
    back to. A CALL always comes back, whatever its arguments' modes.
    """
    caller_state = walk.store.get(walk.program, EMPTY)
    stack = (
        *walk.stack,
        Frame(
            program=row.callee,
            site=walk.node,
            resume=_sequel(loaded.cfg, walk.node),
            crossing=True,
            returns=row.returns or row.transfer == CALL_TRANSFER,
            caller=walk.program,
            windows=windows,
        ),
    )
    return replace(
        walk,
        node=callee.entry,
        stack=stack,
        deps=walk.deps | _arriving(walk, callee.entry, stack, caller_state),
        store={
            **walk.store,
            row.callee: State(
                sources=MappingProxyType(
                    {
                        extent: sources
                        for window in windows
                        for extent, sources in _seeded(
                            caller_state, window.caller_extent, window.callee_extent
                        ).sources.items()
                    }
                )
            ),
        },
    )


def _arriving(
    walk: _Walk, entry: str, stack: tuple[Frame, ...], caller_state: State
) -> frozenset[Dep]:
    """One dep row per window, caller bytes to the callee bytes they become.

    The binding itself moves nothing, but without a row naming both ends a caller
    field whose only further use is to be passed looks like a dead end, and a
    forward query stops at the call. The row is the callee's, at its entry, because
    its target is named in the callee's address space.
    """
    return frozenset(
        Dep(
            program=stack[-1].program,
            node=entry,
            target=window.callee_extent,
            origin="",
            source=window.caller_extent,
            definers=_reached(caller_state, window.caller_extent),
            via=_via(stack),
            source_program=walk.program,
        )
        for window in stack[-1].windows
    )


def _transfer_uncrossable(row: CommareaAlias, windows: tuple[Window, ...]) -> str:
    """A LINK or XCTL needs its commarea window; a CALL needs only a callee to name,
    since an argument with no window is its own dead end, not the site's."""
    if row.transfer not in CROSSING_VERBS:
        return row.reason or f"transfer-not-crossable: {row.transfer}"
    if row.transfer == CALL_TRANSFER:
        return row.reason if not row.callee else ""
    return "" if windows else row.reason or f"transfer-not-crossable: {row.transfer}"


def _callee_unenterable(callee: Loaded) -> str:
    if callee.reason:
        return callee.reason
    if not callee.entry:
        return NO_PROCEDURE
    return ""


def _refusal(
    walk: _Walk, row: CommareaAlias, windows: tuple[Window, ...], callee: Loaded
) -> str:
    """Why this site cannot be crossed, or empty. First reason wins."""
    return (
        _transfer_uncrossable(row, windows)
        or _callee_unenterable(callee)
        or (RE_ENTRY if _open(walk.stack, row.callee, callee.entry) else "")
    )


def _windows(rows: tuple[CommareaAlias, ...]) -> tuple[Window, ...]:
    """The windows a crossing binds: a LINK's or XCTL's one commarea, or one per
    CALL argument that has a window."""
    bound = rows if rows[0].transfer == CALL_TRANSFER else rows[:1]
    return tuple(
        window for window in (_window(row, row.callee) for row in bound) if window.known
    )


def _argument_dead_ends(walk: _Walk, rows: tuple[CommareaAlias, ...]) -> _Walk:
    """A CALL argument with no window -- a literal, a position the callee lists no
    parameter at -- is a dead end of its own; the CALL is still entered."""
    return reduce(
        lambda dead_walk, row: _dead_end(dead_walk, row, row.reason),
        (row for row in rows if row.reason and row.transfer == CALL_TRANSFER),
        walk,
    )


def _called(
    walk: _Walk, loaded: Loaded, loader: Loader, rows: tuple[CommareaAlias, ...]
) -> _Walk:
    """A LINK, an XCTL or a CALL: bind the shared windows and step in, or say why
    not.

    A refusal does not end the caller's path. ``transfer`` has already credited the
    commarea or BY REFERENCE arguments to ``%CALL:<program>`` exactly as the
    fixpoint does, so stopping here would lose the caller's remaining statements and
    gain nothing.
    """
    row = rows[0]
    windows = _windows(rows)
    callee = loader(row.callee) if row.callee else Loaded(program="")
    refused = _refusal(walk, row, windows, callee)
    if refused:
        return _followed(_dead_end(_ran(walk, loaded), row, refused), loaded)
    return _entered(
        _argument_dead_ends(_ran(walk, loaded, windows), rows),
        loaded,
        row,
        windows,
        callee,
    )


def _moved(walk: _Walk, loaded: Loaded, loader: Loader) -> _Walk:
    """Where the path goes from here: into a callee, or along an edge.

    A crossing site is one the alias table has a row for, rather than one this
    module re-recognises by verb. Deriving it from the rows is what makes it
    impossible for the two to disagree about which nodes are call sites.
    """
    rows = loaded.aliases.get(walk.node, ())
    if not rows:
        return _followed(_ran(walk, loaded), loaded)
    return _called(walk, loaded, loader, tuple(rows))


def _stepped(walk: _Walk, loader: Loader) -> _Walk:
    """Run the node the walk stands on, then choose where it goes next."""
    if not walk.running:
        return walk
    return _moved(walk, loader(walk.program), loader)


def _walked(start: _Walk, limit: int, loader: Loader) -> _Walk:
    """Steps until the path ends or ``limit`` nodes have run.

    ``reduce`` over a fixed count rather than a loop with a reassigned accumulator:
    the walk is threaded, and ``_stepped`` returns a finished walk unchanged, so
    the remaining iterations cost one comparison each.
    """
    return reduce(lambda walk, _: _stepped(walk, loader), repeat(None, limit), start)


def _resumed(checkpoint: _Checkpoint, arm: int, max_depth: int) -> _Walk:
    """A walk resumed from a checkpoint with a flipped arm.

    The plan is the prefix of decisions already made plus the flipped arm.
    Past that, arm 0 is taken (the default). Deps, dead_ends, and taken
    start empty -- the resumed walk accumulates only from this point onward.
    ``order`` is seeded from the checkpoint so a PathListener receives the
    complete node sequence from the original path entry, not just the suffix.
    """
    plan = (*(c.taken for c in checkpoint.made), arm)
    return _Walk(
        node=checkpoint.node,
        stack=checkpoint.stack,
        store=checkpoint.store,
        plan=plan,
        made=checkpoint.made,
        entered=checkpoint.entered,
        order=checkpoint.order,
    )


def _started(program: str, loader: Loader, plan: tuple[int, ...]) -> _Walk:
    return _Walk(
        node=loader(program).entry,
        stack=(Frame(program=program),),
        plan=plan,
    )


def _branches(cfg: Cfg) -> int:
    tests = frozenset(node.id for node in cfg.nodes if node.kind is NodeKind.TEST)
    return sum(1 for edge in cfg.edges if edge.source in tests)


def _coverage(before: Coverage, walk: _Walk, loader: Loader) -> Coverage:
    """Taken accumulates; the denominator is recomputed over the programs entered
    so far, so entering a new one raises it rather than flattering the percentage.
    """
    programs = before.programs | walk.entered
    return Coverage(
        taken=before.taken | walk.taken,
        total=sum(_branches(loader(one).cfg) for one in sorted(programs)),
        programs=programs,
    )


def _reported(run: _Run, walk: _Walk, budget: Budget) -> _Run:
    """One line per sampled path, so a long run shows its coverage curve flattening
    rather than showing nothing until the report is written.

    Logged from here rather than from ``_round``'s early return: once the target is
    met that return fires on every remaining path of the budget, and a run that
    stopped at path 2 of 200 would say so 198 times.
    """
    found = run.trace.coverage
    log = logger.warning if walk.running else logger.info
    log(
        "trace: [%d/%d] %d/%d nodes, %d/%d branches (%d%%),"
        " %d programs, %d dead ends, fresh %d uncounted %d stale %d",
        run.trace.paths,
        budget.paths,
        len(walk.order),
        budget.max_depth,
        len(found.taken),
        found.total,
        round(100 * found.fraction),
        len(found.programs),
        len(run.trace.dead_ends),
        len(run.queue.fresh),
        len(run.queue.uncounted),
        len(run.queue.stale),
    )
    return run


EXHAUSTED = "nothing unexplored is reachable"
ONLY_STALE = "every plan left re-flips a branch edge already taken"


def _only_stale(queue: _Queue) -> bool:
    return not queue.fresh and not queue.uncounted and bool(queue.stale)


def _queue_stop(queue: _Queue) -> str:
    """The structural stop the queue signals, or empty when it has more work."""
    if _empty(queue):
        return EXHAUSTED
    if _only_stale(queue):
        return ONLY_STALE
    return ""


def _done(run: _Run, budget: Budget) -> bool:
    return bool(run.stopped or (run.trace.paths and _met(run, budget)))


@dataclass(frozen=True)
class _Stepped:
    """One path walked: the updated run state and the deps it witnessed."""

    run: _Run
    deps: frozenset[Dep]
    dead_ends: frozenset[DeadEnd]
    order: tuple[str, ...] = ()


def _walk_of(head: _Next, program: str, loader: Loader, budget: Budget) -> _Walk:
    """Start a walk from a plan or resume one from a checkpoint."""
    if head.from_checkpoint:
        return _walked(_flipped(head, loader), budget.max_depth, loader)
    return _walked(_started(program, loader, head.plan), budget.max_depth, loader)


def _flipped(head: _Next, loader: Loader) -> _Walk:
    """The resumed walk moved past its decision by the flipped arm.

    Only the move is replayed: the decision node ran on the path that saved the
    checkpoint, so its statement is already in the saved store, and running it again
    would apply that statement twice.
    """
    walk = _resumed(head.checkpoint, head.arm, 0)
    return _followed(walk, loader(walk.program))


def _step(run: _Run, program: str, loader: Loader, budget: Budget) -> _Stepped:
    """Walk one plan and return the new state plus this path's findings.

    The findings are separate so a streaming caller can write them to disk
    without accumulating them in ``Trace.deps``.
    """
    head = _head(run.queue)
    walk = _walk_of(head, program, loader, budget)
    coverage = _coverage(run.trace.coverage, walk, loader)
    next_run = _reported(
        _Run(
            trace=Trace(
                dead_ends=run.trace.dead_ends | walk.dead_ends,
                paths=run.trace.paths + 1,
                coverage=coverage,
            ),
            queue=_extended(
                _drained(run.queue),
                coverage.taken,
                _alternatives(walk, len(head.plan)),
            ),
        ),
        walk,
        budget,
    )
    return _Stepped(
        run=next_run, deps=walk.deps, dead_ends=walk.dead_ends, order=walk.order
    )


def _round(run: _Run, program: str, loader: Loader, budget: Budget) -> _Run:
    if _done(run, budget):
        return run
    reason = _queue_stop(run.queue)
    if reason:
        return replace(run, stopped=reason)
    stepped = _step(run, program, loader, budget)
    return replace(
        stepped.run,
        trace=replace(
            stepped.run.trace,
            deps=run.trace.deps | stepped.deps,
        ),
    )


def _met(run: _Run, budget: Budget) -> bool:
    return run.trace.coverage.fraction >= budget.coverage


def _reachable_programs(
    program: str, loader: Loader, visited: frozenset[str]
) -> frozenset[str]:
    """All programs reachable from ``program`` via alias chains."""
    if program in visited:
        return visited
    loaded = loader(program)
    if not loaded.cfg.nodes:
        return visited
    callees = frozenset(
        alias.callee
        for aliases in loaded.aliases.values()
        for alias in aliases
        if alias.callee and alias.callee not in visited
    )
    return reduce(
        lambda seen, callee: _reachable_programs(callee, loader, seen),
        callees,
        visited | {program},
    )


def _total_nodes(program: str, loader: Loader) -> int:
    return sum(
        len(loader(p).cfg.nodes)
        for p in sorted(_reachable_programs(program, loader, frozenset()))
    )


def _resolved_depth(budget: Budget, loader: Loader, program: str) -> Budget:
    """Fill in max_depth from the reachable programs' total nodes when left at 0."""
    if budget.max_depth:
        return budget
    programs = sorted(_reachable_programs(program, loader, frozenset()))
    total = sum(len(loader(p).cfg.nodes) for p in programs)
    depth = total * (LOOP_ITERATIONS + 1)
    logger.info(
        "trace: auto depth %d (%d nodes across %d programs)",
        depth,
        total,
        len(programs),
    )
    return replace(budget, max_depth=depth)


def traced(program: str, loader: Loader, budget: Budget = DEFAULT_BUDGET) -> Trace:
    """Sample paths from ``program``'s entry until the budget or the coverage target.

    Under-approximate by construction: every dependency here was witnessed by an
    actual path, and absence means "not sampled", never "does not exist".

    Public, and taking a loader rather than a directory, so a caller can hand it
    graphs it built itself. That is the seam the stack rules are asserted through.
    """
    resolved = _resolved_depth(budget, loader, program)
    return _closed(
        reduce(
            lambda run, _: _round(run, program, loader, resolved),
            repeat(None, resolved.paths),
            _Run(),
        ),
        budget,
    ).trace


def _why(run: _Run, budget: Budget) -> str:
    if run.stopped:
        return run.stopped
    if run.trace.coverage.fraction >= budget.coverage:
        return "coverage target met"
    return "path budget ran out"


def _closed(run: _Run, budget: Budget) -> _Run:
    """Why the run stopped, which the per-path lines cannot say. The three reasons ask
    for different responses: a spent budget means raise ``--paths``, a met target means
    this coverage is the ceiling, and an exhausted graph means the fraction below the
    target is the whole truth -- no budget will move it.
    """
    found = run.trace.coverage
    logger.info(
        "trace: %d path%s, %d/%d branches (%d%%), %s",
        run.trace.paths,
        "" if run.trace.paths == 1 else "s",
        len(found.taken),
        found.total,
        round(100 * found.fraction),
        _why(run, budget),
    )
    return run


def visited_order(
    program: str, loader: Loader, budget: Budget = DEFAULT_BUDGET
) -> tuple[str, ...]:
    """The nodes one path ran, in order. ``Trace`` cannot say: it is the union over
    paths, so the route is exactly what it discards."""
    return _walked(_started(program, loader, ()), budget.max_depth, loader).order


@cache
def _loaded(asg_dir: Path, program: str) -> Loaded:
    """Everything a path needs from one member, built once per process.

    Memoised on the directory as well as the name, so a run against a different
    parse never reads another one's answer -- the same reason ``aliases.py`` keys
    its callee reads that way.

    A member whose storage cannot be laid out cannot be entered even when its
    LINKAGE laid out fine, which is what let its call site be aliased in the first
    place: the window says the bytes are shared, not that the callee is analysable.

    An absent cache is the same kind of fact, and the common one: a corpus selection
    LINKs members outside itself, so the callee is a name with no member behind it.
    Refusing it here makes it an opaque block -- the call site credits the commarea,
    control comes back, and the caller's path runs on -- rather than an exception
    that ends a run of hundreds of paths.
    """
    return _built(
        asg_dir,
        program,
        lambda asg, index: _by_node(commarea_aliases(asg, index, asg_dir)),
    )


@cache
def _loaded_alone(asg_dir: Path, program: str) -> Loaded:
    """``_loaded`` with no alias table. No call site is then a crossing, so the
    walk never steps into a callee, the depth budget counts this program alone,
    and no callee's cache is read -- not even to size the shared window."""
    return _built(asg_dir, program, lambda asg, index: NO_ALIASES)


AliasesOf = Callable[[CobolASG, CellIndex], Mapping[str, tuple[CommareaAlias, ...]]]


def _built(asg_dir: Path, program: str, aliases_of: AliasesOf) -> Loaded:
    logger.info("trace: loading %s", program)
    path = asg_dir / f"{program}.json"
    if not path.is_file():
        return Loaded(program=program, reason=f"{NOT_PARSED}: {path}")
    asg = _asg_at(path)
    try:
        index = cell_index(program_records(asg))
    except UnsizeableFieldError as error:
        return Loaded(program=program, reason=f"{UNSIZEABLE}: {error}")
    return Loaded(
        program=program,
        cfg=program_cfg(asg),
        statements=statement_index(asg),
        index=index,
        entry=_entry_node(asg),
        aliases=aliases_of(asg, index),
        files=MappingProxyType(asg.file_record_to_select),
    )


def closure_loader(asg_dir: Path) -> Loader:
    """Every program a path reaches, each loaded as it is first asked for."""
    return lambda member: _loaded(asg_dir, member)


def single_program_loader(asg_dir: Path, program: str) -> Loader:
    """``program`` alone: its own CFG, its call sites run as statements, and any
    other program -- which nothing then asks for -- is a named refusal."""
    return lambda member: (
        _loaded_alone(asg_dir, member)
        if member == program
        else Loaded(program=member, reason=OUTSIDE_SINGLE_PROGRAM)
    )


def _asg_at(path: Path) -> CobolASG:
    """Spelled out here rather than reused: ``aliases.py``'s own reader is private
    to it, and this design's one hard constraint is that nothing existing changes.
    """
    with cached_asg_dialect_parsers_registered():
        return first_program_at(path)


def _entry_node(asg: CobolASG) -> str:
    order = paragraph_order(asg)
    return label_id(order[0].name) if order else ""


def _by_node(
    rows: Sequence[CommareaAlias],
) -> Mapping[str, tuple[CommareaAlias, ...]]:
    """``commarea_aliases`` returns a whole member's sites at once; a path wants one."""
    keys = tuple(dict.fromkeys(row.node for row in rows))
    return {key: tuple(row for row in rows if row.node == key) for key in keys}


def runnable(loaded: Loaded) -> str:
    """Empty when a loaded program has a path to sample, or the reason it has none."""
    return _loaded_unrunnable(loaded)


def _loaded_unrunnable(loaded: Loaded) -> str:
    if loaded.reason:
        return loaded.reason
    if not loaded.entry:
        return NO_PROCEDURE
    return ""


def loadable(asg_dir: Path, program: str) -> str:
    """Empty when ``program`` can be traced, or the reason it cannot.

    The CLI's check, not the walk's: a wrong ``--asg-dir`` is a mistake about the
    invocation rather than a finding about the corpus, and a member with no
    PROCEDURE DIVISION has no path to sample.
    """
    path = asg_dir / f"{program}.json"
    if not path.is_file():
        return f"no ASG cache at {path}"
    loaded = _loaded(asg_dir, program)
    return _loaded_unrunnable(loaded)


def sampled(program: str, asg_dir: Path, budget: Budget = DEFAULT_BUDGET) -> Trace:
    """``traced`` against the one ASG cache every other stage reads.

    No artefact directory: reading the cache directly is what lets a path enter a
    callee ``aliases.jsonl`` has no rows for, which is any member a single-member
    build did not select.
    """
    return traced(program, closure_loader(asg_dir), budget)


Sink = Callable[[frozenset[Dep]], None]

PathListener = Callable[[tuple[str, ...]], None]
"""Called with the ordered node sequence of every completed path.

The listener decides what to do -- filter by target node, write to disk,
accumulate statistics.  Pass ``_ignore_path`` (the default) to preserve
existing behaviour; every existing call site sees no change.
"""


def _ignore_path(_order: tuple[str, ...]) -> None:
    """No-op PathListener used as the default sentinel."""


def _streamed_round(
    run: _Run,
    program: str,
    loader: Loader,
    budget: Budget,
    sink: Sink,
    path_listener: PathListener = _ignore_path,
) -> _Run:
    if _done(run, budget):
        return run
    reason = _queue_stop(run.queue)
    if reason:
        return replace(run, stopped=reason)
    stepped = _step(run, program, loader, budget)
    sink(stepped.deps)
    path_listener(stepped.order)
    return stepped.run


def streamed(
    program: str,
    loader: Loader,
    budget: Budget,
    sink: Sink,
    path_listener: PathListener = _ignore_path,
) -> Trace:
    """Like ``traced`` but writes each path's deps through ``sink`` immediately.

    ``Trace.deps`` in the returned value is empty -- the deps are on disk, not
    in memory. Everything else (coverage, dead_ends, paths) is populated.

    ``path_listener``, when given, is called with the ordered node sequence of
    every completed path.  The listener decides what to record; the dep stream
    is unaffected.  Omit it (or pass ``_ignore_path``) for the original behaviour.
    """
    resolved = _resolved_depth(budget, loader, program)
    return _closed(
        reduce(
            lambda run, _: _streamed_round(
                run, program, loader, resolved, sink, path_listener
            ),
            repeat(None, resolved.paths),
            _Run(),
        ),
        resolved,
    ).trace
