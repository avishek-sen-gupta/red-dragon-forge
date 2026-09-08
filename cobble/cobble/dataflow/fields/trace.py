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

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache, reduce
from itertools import repeat
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.aliases import NO_EXTENT, UNSIZEABLE, commarea_aliases
from cobble.dataflow.fields.extent import CellIndex, cell_index
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.state import EMPTY, Source, State, reaching, write
from cobble.dataflow.fields.transfer import Statement, Write, writes_of
from cobble.dataflow.layout import UnsizeableFieldError, program_records
from cobble.dataflow.srccfg.build import build_program, label_id, paragraph_order
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, NodeKind
from cobble.dataflow.srccfg.desugar import LINK_TRANSFER, XCTL_TRANSFER
from cobble.dataflow.srccfg.statements import statement_index
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

logger = logging.getLogger(__name__)

DEFAULT_PATHS = 200
DEFAULT_COVERAGE = 1.0
DEFAULT_MAX_DEPTH = 5000

CROSSING_VERBS = (LINK_TRANSFER, XCTL_TRANSFER)

NO_PROCEDURE = "callee-has-no-procedure"
NOT_PARSED = "callee-not-parsed"
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
    """A commarea's two ends: the caller's bytes and the callee's, same length.

    ``known`` False is a call site with no window to bind -- a dynamic target, a
    callee absent from the cache, an operand naming no field. A sentinel rather
    than an absent value, so a caller compares windows the same way everywhere.
    """

    caller: str = ""
    caller_extent: FieldExtent = NO_EXTENT
    callee_extent: FieldExtent = NO_EXTENT
    known: bool = False


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
    """

    program: str
    node: str
    target: FieldExtent
    origin: str
    source: FieldExtent
    definers: tuple[str, ...]
    via: str


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
        caller=row.caller, caller_extent=caller, callee_extent=landed, known=True
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
        for extent, sources in held.items()
        if extent.may_alias(source)
    )
    keys = tuple(dict.fromkeys(extent for extent, _ in bound))
    return {
        key: frozenset(
            one for extent, sources in bound if extent == key for one in sources
        )
        for key in keys
    }


NO_CFG = Cfg(program="", nodes=(), edges=())
NO_INDEX = cell_index(())
NO_STATEMENTS: Mapping[str, Statement] = MappingProxyType({})
NO_ALIASES: Mapping[str, tuple[CommareaAlias, ...]] = MappingProxyType({})
NO_STORE: Mapping[str, State] = MappingProxyType({})
NO_CURSORS: Mapping[tuple[str, str], int] = MappingProxyType({})


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
    reason: str = ""


Loader = Callable[[str], Loaded]


@dataclass(frozen=True)
class Frame:
    """One open invocation: where it resumes, and which nodes it has already run.

    Popped whole on return, which is what makes the re-entry rule right in all
    three of its cases. A paragraph's visited nodes leave with its frame, so a
    second PERFORM of the same paragraph starts clean; a frame still open still
    forbids re-entry, which covers a loop's back edge, a recursive PERFORM and a
    LINK cycle with one rule.
    """

    program: str
    site: str = ""
    resume: str = ""
    crossing: bool = False
    returns: bool = False
    window: Window = NO_WINDOW
    visited: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Walk:
    """One path, mid-flight. Threaded, never mutated."""

    node: str
    stack: tuple[Frame, ...]
    store: Mapping[str, State] = NO_STORE
    cursors: Mapping[tuple[str, str], int] = NO_CURSORS
    deps: frozenset[Dep] = frozenset()
    dead_ends: frozenset[DeadEnd] = frozenset()
    taken: frozenset[tuple[str, str, str]] = frozenset()
    entered: frozenset[str] = frozenset()
    order: tuple[str, ...] = ()
    running: bool = True

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
        crossings = tuple(one for one in self.stack if one.crossing)
        if not crossings:
            return ""
        return f"{crossings[-1].window.caller}/{crossings[-1].site}"


@dataclass(frozen=True)
class _Run:
    """The sampler's accumulator: the trace so far, and the cursors that make the
    next path differ from the last one."""

    trace: Trace = Trace()
    cursors: Mapping[tuple[str, str], int] = NO_CURSORS


def _open(stack: Sequence[Frame], program: str, node: str) -> bool:
    """The re-entry rule: an edge back to a node an open frame has already run."""
    return any(one.program == program and node in one.visited for one in stack)


def _marked(stack: tuple[Frame, ...], node: str) -> tuple[Frame, ...]:
    return (*stack[:-1], replace(stack[-1], visited=stack[-1].visited | {node}))


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
    return tuple(sorted({one.node for one in reaching(held, source.extent)}))


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
        )
        for entry in writes
        for one in entry.sources
    )


def _applied(held: State, writes: Sequence[Write]) -> State:
    return reduce(
        lambda state, entry: write(state, entry.target, entry.sources), writes, held
    )


def _ran(walk: _Walk, loaded: Loaded) -> _Walk:
    """This node's statement against this program's slice, and what it witnessed."""
    held = walk.store.get(walk.program, EMPTY)
    writes = _writes(walk, loaded)
    return replace(
        walk,
        stack=_marked(walk.stack, walk.node),
        store={**walk.store, walk.program: _applied(held, writes)},
        deps=walk.deps | _witnessed(walk, held, writes),
        entered=walk.entered | {walk.program},
        order=(*walk.order, walk.node),
    )


def _sequel(cfg: Cfg, node: str) -> str:
    """Where a call or a PERFORM continues once it comes back.

    This node's own FLOW edge, which ``build.py`` keeps even on a PERFORM node --
    purely so the paragraph's RETURN targets can be computed from it.
    """
    return next(
        (edge.target for edge in cfg.successors(node) if edge.kind is EdgeKind.FLOW),
        "",
    )


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


def _admissible(walk: _Walk, edges: Sequence[Edge]) -> tuple[Edge, ...]:
    """Everything left once the stack has had its say.

    PERFORM edges are gone because a refused one means the paragraph is skipped and
    this node's own FLOW edge is the continuation. RETURN edges are gone because
    the path reached this node without performing it -- by falling through -- and
    its callers' resume points are none of its business.
    """
    return tuple(
        one
        for one in edges
        if one.kind is not EdgeKind.PERFORM
        and one.kind is not EdgeKind.RETURN
        and not _open(walk.stack, walk.program, one.target)
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


def _sampled(walk: _Walk, loaded: Loaded, edges: Sequence[Edge]) -> _Walk:
    """One branch, chosen by this node's cursor, which advances across paths.

    The cursor is per (program, node) and global to the run, so path 1 takes a
    node's first arm and path 2 its second. Deterministic and reproducible, which
    is why no random seed appears anywhere here.
    """
    if not edges:
        return _ended(walk)
    key = (walk.program, walk.node)
    seen = walk.cursors.get(key, 0)
    chosen = edges[seen % len(edges)]
    return replace(
        walk,
        node=chosen.target,
        cursors={**walk.cursors, key: seen + 1},
        taken=walk.taken | _branch(loaded, walk.node, chosen),
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


def _restored(caller: State, callee: State, window: Window) -> State:
    """The caller's slice with the shared window written back from the callee's.

    ``state.write`` rather than a union: the callee's write to those bytes really
    did kill what the caller held there, and ``must_cover`` is what says so. Not
    ``state.join``, which is the fixpoint's operation and is never called here.

    The callee's slice can hold overlapping extents -- a group and its elementary
    items both defined. Sequential ``write`` per extent has to pick an order, and
    widest-first is chosen so the narrow, specific definitions are the ones that
    survive ``must_cover``'s kills.
    """
    back = _seeded(callee, window.callee_extent, window.caller_extent)
    return reduce(
        lambda held, pair: write(held, pair[0], pair[1]),
        sorted(
            back.items(),
            key=lambda pair: (
                pair[0].region.value,
                pair[0].start,
                -pair[0].length,
                pair[0].field_name,
            ),
        ),
        caller,
    )


def _unwound(stack: tuple[Frame, ...]) -> tuple[Frame, ...]:
    """The stack cut back to its innermost crossing frame, empty when it has none.

    A callee's path can end inside a PERFORMed paragraph, so the frame on top when
    the path runs out is not necessarily the frame that owes a caller its bytes.
    """
    crossings = tuple(index for index, frame in enumerate(stack) if frame.crossing)
    return stack[: crossings[-1] + 1] if crossings else ()


def _ended(walk: _Walk) -> _Walk:
    """Nowhere left to go, unless a crossing frame owes its caller a return.

    Seeding the caller's window back needs no conversion and no flow edge: the two
    sides were the same bytes all along. An empty resume point is a call that was
    the last thing its caller did, so there is nothing to come back to.
    """
    unwound = _unwound(walk.stack)
    if not unwound:
        return replace(walk, running=False)
    frame = unwound[-1]
    if not (frame.returns and frame.resume):
        return replace(walk, running=False)
    return replace(
        walk,
        node=frame.resume,
        stack=unwound[:-1],
        store={
            **walk.store,
            frame.window.caller: _restored(
                walk.store.get(frame.window.caller, EMPTY),
                walk.store.get(frame.program, EMPTY),
                frame.window,
            ),
        },
    )


def _followed(walk: _Walk, loaded: Loaded) -> _Walk:
    """Along an edge. PERFORM and RETURN are decided by the stack; the rest sampled.

    A PERFORM edge is always taken rather than sampled: the FLOW edge beside it is
    a bookkeeping artefact of ``build.py``, and taking it would skip the paragraph.
    A refused PERFORM -- its target is on the stack -- falls through to the FLOW
    edge, which skips the paragraph rather than abandoning the path.
    """
    edges = loaded.cfg.successors(walk.node)
    performed = tuple(one for one in edges if one.kind is EdgeKind.PERFORM)
    if performed and not _open(walk.stack, walk.program, performed[0].target):
        return _performed(walk, loaded, performed[0])
    returned = _return_edge(walk, edges)
    if returned:
        return _returned(walk, returned[0])
    return _sampled(walk, loaded, _admissible(walk, edges))


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
    window: Window,
    callee: Loaded,
) -> _Walk:
    """Step into the callee with the shared window bound, and nothing else.

    The callee's slice starts empty because CICS gives a LINKed program fresh
    WORKING-STORAGE, so a program entered twice on one path does not inherit its
    own earlier run's memory. The resume point is read off the CALLER's graph:
    that is where the path comes back to.
    """
    return replace(
        walk,
        node=callee.entry,
        stack=(
            *walk.stack,
            Frame(
                program=row.callee,
                site=walk.node,
                resume=_sequel(loaded.cfg, walk.node),
                crossing=True,
                returns=row.returns,
                window=window,
            ),
        ),
        store={
            **walk.store,
            row.callee: _seeded(
                walk.store.get(walk.program, EMPTY),
                window.caller_extent,
                window.callee_extent,
            ),
        },
    )


def _transfer_uncrossable(row: CommareaAlias, window: Window) -> str:
    if row.transfer not in CROSSING_VERBS or not window.known:
        return row.reason or f"transfer-not-crossable: {row.transfer}"
    return ""


def _callee_unenterable(callee: Loaded) -> str:
    if callee.reason:
        return callee.reason
    if not callee.entry:
        return NO_PROCEDURE
    return ""


def _refusal(walk: _Walk, row: CommareaAlias, window: Window, callee: Loaded) -> str:
    """Why this site cannot be crossed, or empty. First reason wins.

    A CALL ... USING row is refused by its transfer: the caller's parameters bind
    positionally onto the callee's PROCEDURE DIVISION USING, which is a different
    relation from a commarea window and is deliberately out of scope. Its own row
    already carries ``call-using-unsupported``, so nothing here has to invent a
    reason for it.
    """
    return (
        _transfer_uncrossable(row, window)
        or _callee_unenterable(callee)
        or (RE_ENTRY if _open(walk.stack, row.callee, callee.entry) else "")
    )


def _called(walk: _Walk, loaded: Loaded, loader: Loader, row: CommareaAlias) -> _Walk:
    """A LINK or an XCTL: bind the shared window and step in, or say why not.

    A refusal does not end the caller's path. ``transfer`` has already credited the
    commarea to ``%CALL:<program>`` exactly as the fixpoint does, so stopping here
    would lose the caller's remaining statements and gain nothing.
    """
    window = _window(row, row.callee)
    callee = loader(row.callee) if row.callee else Loaded(program="")
    refused = _refusal(walk, row, window, callee)
    if refused:
        return _followed(_dead_end(walk, row, refused), loaded)
    return _entered(walk, loaded, row, window, callee)


def _moved(walk: _Walk, loaded: Loaded, loader: Loader) -> _Walk:
    """Where the path goes from here: into a callee, or along an edge.

    A crossing site is one the alias table has a row for, rather than one this
    module re-recognises by verb. Deriving it from the rows is what makes it
    impossible for the two to disagree about which nodes are call sites.
    """
    rows = loaded.aliases.get(walk.node, ())
    if not rows:
        return _followed(walk, loaded)
    return _called(walk, loaded, loader, rows[0])


def _stepped(walk: _Walk, loader: Loader) -> _Walk:
    """Run the node the walk stands on, then choose where it goes next."""
    if not walk.running:
        return walk
    loaded = loader(walk.program)
    return _moved(_ran(walk, loaded), loaded, loader)


def _walked(start: _Walk, limit: int, loader: Loader) -> _Walk:
    """Steps until the path ends or ``limit`` nodes have run.

    ``reduce`` over a fixed count rather than a loop with a reassigned accumulator:
    the walk is threaded, and ``_stepped`` returns a finished walk unchanged, so
    the remaining iterations cost one comparison each.
    """
    return reduce(lambda walk, _: _stepped(walk, loader), repeat(None, limit), start)


def _started(
    program: str, loader: Loader, cursors: Mapping[tuple[str, str], int]
) -> _Walk:
    return _Walk(
        node=loader(program).entry,
        stack=(Frame(program=program),),
        cursors=cursors,
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
    logger.info(
        "trace: [%d/%d] %d nodes, %d/%d branches (%d%%), %d programs, %d dead ends",
        run.trace.paths,
        budget.paths,
        len(walk.order),
        len(found.taken),
        found.total,
        round(100 * found.fraction),
        len(found.programs),
        len(run.trace.dead_ends),
    )
    return run


def _round(run: _Run, program: str, loader: Loader, budget: Budget) -> _Run:
    """One path, unless the coverage target is already met."""
    if run.trace.paths and run.trace.coverage.fraction >= budget.coverage:
        return run
    walk = _walked(_started(program, loader, run.cursors), budget.max_depth, loader)
    return _reported(
        _Run(
            trace=Trace(
                deps=run.trace.deps | walk.deps,
                dead_ends=run.trace.dead_ends | walk.dead_ends,
                paths=run.trace.paths + 1,
                coverage=_coverage(run.trace.coverage, walk, loader),
            ),
            cursors=walk.cursors,
        ),
        walk,
        budget,
    )


def traced(program: str, loader: Loader, budget: Budget = DEFAULT_BUDGET) -> Trace:
    """Sample paths from ``program``'s entry until the budget or the coverage target.

    Under-approximate by construction: every dependency here was witnessed by an
    actual path, and absence means "not sampled", never "does not exist".

    Public, and taking a loader rather than a directory, so a caller can hand it
    graphs it built itself. That is the seam the stack rules are asserted through.
    """
    return _closed(
        reduce(
            lambda run, _: _round(run, program, loader, budget),
            repeat(None, budget.paths),
            _Run(),
        ),
        budget,
    ).trace


def _closed(run: _Run, budget: Budget) -> _Run:
    """Why the run stopped, which the per-path lines cannot say. The two reasons ask
    for opposite responses: a spent budget means raise ``--paths``, a met target
    means this coverage is the ceiling.
    """
    found = run.trace.coverage
    logger.info(
        "trace: %d path%s, %d/%d branches (%d%%), %s",
        run.trace.paths,
        "" if run.trace.paths == 1 else "s",
        len(found.taken),
        found.total,
        round(100 * found.fraction),
        (
            "coverage target met"
            if found.fraction >= budget.coverage
            else "path budget ran out"
        ),
    )
    return run


def visited_order(
    program: str, loader: Loader, budget: Budget = DEFAULT_BUDGET
) -> tuple[str, ...]:
    """The nodes one path ran, in order. ``Trace`` cannot say: it is the union over
    paths, so the route is exactly what it discards."""
    return _walked(
        _started(program, loader, NO_CURSORS), budget.max_depth, loader
    ).order


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
        cfg=build_program(asg),
        statements=statement_index(asg),
        index=index,
        entry=_entry_node(asg),
        aliases=_by_node(commarea_aliases(asg, index, asg_dir)),
    )


def _asg_at(path: Path) -> CobolASG:
    """Spelled out here rather than reused: ``aliases.py``'s own reader is private
    to it, and this design's one hard constraint is that nothing existing changes.
    """
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _entry_node(asg: CobolASG) -> str:
    order = paragraph_order(asg)
    return label_id(order[0].name) if order else ""


def _by_node(
    rows: Sequence[CommareaAlias],
) -> Mapping[str, tuple[CommareaAlias, ...]]:
    """``commarea_aliases`` returns a whole member's sites at once; a path wants one."""
    keys = tuple(dict.fromkeys(row.node for row in rows))
    return {key: tuple(row for row in rows if row.node == key) for key in keys}


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
    return traced(program, lambda member: _loaded(asg_dir, member), budget)
