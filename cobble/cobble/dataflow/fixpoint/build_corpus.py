"""The field dataflow corpus pass.

No JVM. Two inputs: the ASG cache, and the ``extents.jsonl`` ``cobble-extents``
wrote over that same cache. This stage computes no extent of its own -- a member's
records are read back out of that table, and the walk is seeded from the VALUE
image of exactly those records. The table is required, because a layout invented
here could disagree with the published one and nothing would say so. A member the
table does not hold is a recorded skip naming the command that fixes it, never a
crash and never silence.

The table drives the run: it is streamed one member at a time and each member's
records are dropped before the next arrives, so the memory is the largest member's
layout rather than the corpus's -- 29 members' cells held at once are 1.5GB of
objects, and the corpora this is for are ten times longer. What that costs is the
order: members are analysed in the order the table holds them, which for --all is
the sorted order they were already in, and for --member is no longer the order they
were named in. The selection still decides what is analysed, and a selected member
the table does not hold is reported after the ones it does.

A member that raises is reported and the run continues, because the answer wanted
from a whole-corpus run is "which members are missing from this output", and a run
that aborts answers that for one member only.

Five files, so that the graph holds only what nothing outside it could state:

  graph.jsonl    the FIELD endpoints (no attributes) and one FLOWS_TO per
                 (node, source extent, target extent), each row tagged node or edge
  defs.jsonl     the definitions reaching each (node, source extent)
  aliases.jsonl  per call site and caller window, the bytes shared with a callee
  targets.jsonl  per dynamic call site, the candidate programs it can reach
  jumps.jsonl    per jump, exit, RETRIEVE and entry, what it hands over

An aliases row is one LINK/XCTL/CALL site and one caller window: the bytes the
caller and the callee both address, or the named reason they share none. The
window is in the key because a commarea name declared in two records resolves to
two caller cells on different bytes, so one site contributes a row per resolution
-- ``aliased`` counts the sites, not the rows. A member the walk's budget gave up
on still contributes its rows, since they need the caller's layout and not the
walk. Two members contribute none: one whose own cache file will not parse, which
raises before the alias pass runs and is named in the skipped list instead, and
one whose layout never built at all -- the unsizeable-field skip, which no input
reaches today.

How many sites reached a window, and what stopped the rest, are the summary's
``aliased`` and ``alias_dead_ends``. They are not a partition of the site count:
one of a twice-declared commarea name's two cells can share a window while the
other is a zero-length range nothing can be crossed through, which puts that one
site in both. The table's cost is a full parse of every distinct callee's cache
file, once per run, for its LINKAGE alone.

extents and defs are relations of their own rather than edge attributes
because both are many-to-one against a flow: one read has as many reaching
definitions as it has paths, and one byte range as many declared names as it has
groups and redefinitions over it. Held on the edge they were duplicated per path
and deduplicated by endpoint, which dropped all but one. ``fields.query`` joins
them back; nothing about a flow is recoverable only from a fan-out.

The graph is intra-program: a CALL or LINK contributes a synthetic %CALL:<target>
source and no callee summary. aliases.jsonl states which bytes that site shares
with its callee, but it is not an edge -- naming several members analyses each one
independently, so no edge crosses a program.

Exactly one of --member and --all is required. The usual question is about the
fields of one program, so a whole-cache pass is asked for rather than defaulted
into: a run nobody meant to start is minutes of fixpoint per member.

--sweeps trades completeness for cost, and says which it got. A member that
settles inside its budget is exactly as complete as the worklist's answer; one
that does not is a subset of its flows, reported as unsettled in the summary and
warned about by name. Neither is a skip: nothing is invented either way.

Exit status contract:
  0 - every member analysed, coverage at or above the floor
  1 - coverage below the floor
  2 - ASG directory not found, extents table not found, or a --member the cache
      does not hold
  3 - one or more members skipped, unreadable, absent from the extents table, or
      colliding on program_id
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from functools import reduce
from itertools import (
    accumulate,
    groupby,
    islice,
    repeat,
    takewhile,
)
from operator import itemgetter
from pathlib import Path
from types import MappingProxyType

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_index import CorpusIndex, FileLocationResolver
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.aliases import (
    ALIAS_PHASE_FAILED,
    UNREADABLE,
    commarea_aliases,
)
from cobble.dataflow.fields.emit import graph_records
from cobble.dataflow.fields.emit_extents import worker_count
from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.extents_input import (
    MemberLayout,
    member_layout,
    member_rows,
)
from cobble.dataflow.fields.program_layout import ProgramLayout
from cobble.dataflow.fields.side_tables import (
    CommareaAlias,
    JsonlWriter,
    ReachingDefs,
    alias_identity,
    alias_row,
    defs_identity,
    defs_row,
    jsonl_writer,
    target_identity,
    target_row,
)
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.fixpoint.area_need_file import read_rows, table_of
from cobble.dataflow.fixpoint.fixpoint import NO_INDEX, ProgramFlow, analysed
from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.dataflow.fixpoint.options import ITERATION_FACTOR, AnalysisOptions
from cobble.dataflow.fixpoint.rows import Row
from cobble.dataflow.fixpoint.scope import Scope
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.targets import ResolvedTarget
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.rows import jump_identity, jump_row
from cobble.knowledge_graph.graph_file import read_graph_rows
from cobble.knowledge_graph.graph_types import GraphEdge, GraphNode
from cobble.knowledge_graph.graph_writer import GraphWriter, graph_writer
from cobble.parsing.asg_cache import first_program_at
from cobble.path_utils import ensure_dir
from cobol_asg.asg_types import CobolASG
from pydantic import ValidationError

logger = logging.getLogger(__name__)

GRAPH_FILE = "graph.jsonl"
DEFS_FILE = "defs.jsonl"
ALIASES_FILE = "aliases.jsonl"
TARGETS_FILE = "targets.jsonl"
JUMPS_FILE = "jumps.jsonl"
MEMBERS_DIR = "members"
COUNTS_FILE = "counts.json"
DEFAULT_FLOOR = 0.60


@dataclass(frozen=True)
class MemberResult:
    """One member's records and counters, or the reason it produced none.

    ``settled`` False means the walk's budget ran out while the state was still
    growing: the records are a subset of the member's flows. Not a skip -- the
    edges are real -- but it has to be visible, or a budgeted run reads as a
    complete one.
    """

    member: str
    program: str = ""
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    defs: tuple[ReachingDefs, ...] = ()
    aliases: tuple[CommareaAlias, ...] = ()
    targets: tuple[ResolvedTarget, ...] = ()
    jumps: tuple[Jump, ...] = ()
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    unmodelled: int = 0
    sweeps: int = 0
    settled: bool = True
    skipped: str = ""
    scope: Scope = Scope.WHOLE
    tracked: int = 0
    relevant: int = 0


@dataclass(frozen=True)
class RunTotals:
    """The run so far. ``programs`` is every (program_id, member) pair seen.

    Pairs rather than a map on the program_id: a program_id declared by two members
    is normal on a real corpus, and a map on it would hold the last member and lose
    the others without saying so.

    ``members`` is every member this run reached, which is how a selected member
    the extents table never yielded is told from one it did. Names only -- the
    results themselves are written and dropped as they are produced.
    """

    members: tuple[str, ...] = ()
    analysed: int = 0
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    unmodelled: int = 0
    skipped: tuple[tuple[str, str], ...] = ()
    unsettled: tuple[str, ...] = ()
    programs: tuple[tuple[str, str], ...] = ()
    aliased: int = 0
    dead_ends: tuple[str, ...] = ()
    dynamic_sites: int = 0
    resolved_one: int = 0
    resolved_several: int = 0
    unresolved_reasons: tuple[str, ...] = ()
    file_sites: int = 0
    file_resolved_one: int = 0
    file_resolved_several: int = 0

    @property
    def coverage(self) -> float:
        return self.covered / self.writes if self.writes else 0.0


def _summary(totals: RunTotals) -> dict[str, float | int | Mapping[str, int]]:
    return {
        "analysed": totals.analysed,
        "writes": totals.writes,
        "covered": totals.covered,
        "coverage": round(totals.coverage, 4),
        "unhandled": totals.unhandled,
        "unmodelled": totals.unmodelled,
        "skipped": len(totals.skipped),
        "unsettled": len(totals.unsettled),
        "collisions": len(_duplicates(totals)),
        "aliased": totals.aliased,
        "alias_dead_ends": _tallied(totals.dead_ends),
    }


_CARRY_AN_ERROR = (UNREADABLE, ALIAS_PHASE_FAILED)


def _bucket(reason: str) -> str:
    """The key a dead end tallies under.

    Every reason is a fixed string except the two that carry an error's repr.
    Tallied verbatim either of those fragments into one key of count one per
    distinct message, so both bucket under their prefix and the error text is left
    to the rows.
    """
    return next(
        (prefix for prefix in _CARRY_AN_ERROR if reason.startswith(prefix)), reason
    )


def _tallied(reasons: Sequence[str]) -> Mapping[str, int]:
    """How many sites stopped for each reason, so the table's coverage is stated
    rather than assumed."""
    buckets = tuple(_bucket(reason) for reason in reasons)
    return {bucket: buckets.count(bucket) for bucket in dict.fromkeys(buckets)}


def _duplicates(totals: RunTotals) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every program_id more than one member declares, with those members."""
    grouped = groupby(sorted(totals.programs), key=itemgetter(0))
    named = (
        (program, tuple(member for _, member in rows)) for program, rows in grouped
    )
    return tuple((program, members) for program, members in named if len(members) > 1)


def _tables(
    member: str,
    flow: ProgramFlow,
    layout: ProgramLayout,
    locations: FileLocationResolver,
) -> MemberResult:
    """The graph tables, or the reason this member has none of them."""
    if flow.skipped:
        return MemberResult(member=member, program=flow.program, skipped=flow.skipped)
    records = graph_records(flow, layout, locations)
    return MemberResult(
        member=member,
        program=flow.program,
        nodes=records.nodes,
        edges=records.edges,
        defs=records.defs,
        targets=flow.targets,
        jumps=flow.jumps,
        writes=flow.writes,
        covered=flow.covered,
        unhandled=flow.unhandled,
        unmodelled=flow.unmodelled,
        sweeps=flow.sweeps,
        settled=flow.settled,
        tracked=flow.tracked,
        relevant=flow.relevant,
    )


def _alias_rows(
    asg: CobolASG, index: CellIndex, asg_dir: Path
) -> tuple[CommareaAlias, ...]:
    """Walled off from the four tables the alias pass has nothing to do with.

    The one wall, and deliberately at member scope: the alternative is an alias
    nobody asked for costing this member its four tables and the run its exit code.
    A finer wall per call site would file our own bugs as artefact rows and hide
    them, so an unknown defect here costs the whole member's alias rows and is
    reported by name. Its own reason rather than ``unreadable``, which is a broken
    cache file the corpus owns: this row says the alias phase itself gave up -- a bug
    nothing outside this repo can fix. ``node`` and ``transfer`` are blank because no
    site was reached to name.
    """
    try:
        return commarea_aliases(asg, index, asg_dir)
    except Exception as error:  # noqa: BLE001 - an alias costs one row, never a table
        return (
            CommareaAlias(
                caller=asg.program_id,
                node="",
                transfer="",
                reason=f"{ALIAS_PHASE_FAILED}: {error!r}",
            ),
        )


def _aliased_member(
    result: MemberResult, asg: CobolASG, index: CellIndex, asg_dir: Path
) -> MemberResult:
    """The alias rows added to a member whose records are already settled.

    A member the walk gave up on keeps its rows: the alias table needs the
    caller's layout and the dequeue cap is reached long after that layout is
    built, so withholding them would report "this program calls nothing" for
    exactly the members whose callees a reader is asking about. ``NO_INDEX`` is
    the silence -- ``analysed`` returns it for an unsizeable field, where no layout
    was ever computed and there is no caller window to name. No input reaches it
    today: the error needs a COMP field over 31 digits and ``parse_pic`` rejects
    anything over 18 first. That same root cause makes the ``unsizeable`` dead-end
    reason unreachable, in a callee's LINKAGE rather than a caller's own layout.
    Kept because the sentinel is ``analysed``'s stated contract, and rows claiming a
    window here would claim one that never existed.
    """
    if index is NO_INDEX:
        return result
    return replace(result, aliases=_alias_rows(asg, index, asg_dir))


def _analysed_member(
    published: MemberLayout,
    path: Path,
    options: AnalysisOptions,
    locations: FileLocationResolver,
) -> MemberResult:
    """The four tables first, then the aliases folded onto them.

    In that order because the alias pass cannot discard what it never held -- the
    four tables are already in the result it replaces by the time it runs.

    The layout arrives from the extents table, never from this program's DATA
    DIVISION: this stage computes no extent of its own, so the records the walk is
    seeded from are the same ones ``cobble-extents`` published.
    """
    asg = first_program_at(path)
    flow, index = analysed(
        asg,
        replace(options, areas=options.areas.seen_from(published.member)),
        published.layout,
    )
    tables = replace(
        _tables(published.member, flow, published.layout, locations),
        scope=options.scope,
    )
    return _aliased_member(tables, asg, index, path.parent)


def _no_extents(path: Path, extents: Path) -> str:
    """The reason a member the extents table does not hold produces no rows.

    A reason and not a crash, for the same cause the unsizeable skip exists for: a
    member whose layout this run does not have is one member missing from the
    output, and the run still has to say which. Names the command that fixes it,
    because nothing else about the artefact says the table is an input.
    """
    return (
        f"no rows in {extents.name}: run cobble-extents "
        f"--asg-dir {path.parent} --out {extents} {path.stem}"
    )


def _member_result(
    published: MemberLayout,
    path: Path,
    options: AnalysisOptions,
    locations: FileLocationResolver,
) -> MemberResult:
    """Every failure one member can have, as a reason rather than an abort.

    The records are built before anything is written, so a member that raises
    halfway through leaves no partial rows behind it.
    """
    try:
        return _analysed_member(published, path, options, locations)
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        return MemberResult(
            member=published.member,
            skipped=f"unreadable: {error!r}",
            scope=options.scope,
        )


def _skipped(counts: MemberCounts) -> tuple[tuple[str, str], ...]:
    return ((counts.member, counts.skipped),) if counts.skipped else ()


def _seen(counts: MemberCounts) -> tuple[tuple[str, str], ...]:
    return ((counts.program, counts.member),) if counts.program else ()


def _unsettled(counts: MemberCounts) -> tuple[str, ...]:
    return () if counts.skipped or counts.settled else (counts.member,)


def _site(alias: CommareaAlias) -> tuple[str, str]:
    return (alias.caller, alias.node)


def _aliased(result: MemberResult) -> int:
    """Sites that reached a window, not rows. One commarea name declared in two
    records resolves to two caller cells, so one site is legitimately two rows."""
    return len({_site(alias) for alias in result.aliases if not alias.reason})


def _dead_ends(result: MemberResult) -> tuple[str, ...]:
    """One reason per site that stopped for it, so the tally counts what
    ``aliased`` counts. Keyed through a dict rather than a set because the tally's
    key order is the summary's and a set's order is the hash seed's."""
    stopped = {
        (*_site(alias), alias.reason): alias.reason
        for alias in result.aliases
        if alias.reason
    }
    return tuple(stopped.values())


def _of_kind(result: MemberResult, kind: TargetKind) -> tuple[ResolvedTarget, ...]:
    return tuple(target for target in result.targets if target.kind is kind)


def _resolved_one(targets: Sequence[ResolvedTarget]) -> int:
    return sum(1 for target in targets if len(target.candidates) == 1)


def _resolved_several(targets: Sequence[ResolvedTarget]) -> int:
    return sum(1 for target in targets if len(target.candidates) > 1)


def _unresolved_reasons(result: MemberResult) -> tuple[str, ...]:
    """Why a site resolved to no program, one entry per reason it carries.

    Only sites with no candidates: one carrying both candidates and a reason --
    the menu table's ``uninitialised`` alongside ten resolved names -- answered
    the question already, so it is not a none. A site can carry more than one
    reason, so this does not partition ``dynamic_sites`` and is not made to."""
    return tuple(
        reason.value
        for target in _of_kind(result, TargetKind.PROGRAM)
        if not target.candidates
        for reason in target.reasons
    )


def counts_of(result: MemberResult) -> MemberCounts:
    """What a member adds to the run's report, without the records themselves."""
    calls = _of_kind(result, TargetKind.PROGRAM)
    files = _of_kind(result, TargetKind.FILE)
    return MemberCounts(
        member=result.member,
        program=result.program,
        skipped=result.skipped,
        writes=result.writes,
        covered=result.covered,
        unhandled=result.unhandled,
        unmodelled=result.unmodelled,
        sweeps=result.sweeps,
        settled=result.settled,
        edges=len(result.edges),
        aliased=_aliased(result),
        dead_ends=_dead_ends(result),
        dynamic_sites=len(calls),
        resolved_one=_resolved_one(calls),
        resolved_several=_resolved_several(calls),
        unresolved_reasons=_unresolved_reasons(result),
        file_sites=len(files),
        file_resolved_one=_resolved_one(files),
        file_resolved_several=_resolved_several(files),
        scope=result.scope,
        tracked=result.tracked,
        relevant=result.relevant,
    )


def _folded(totals: RunTotals, counts: MemberCounts) -> RunTotals:
    return RunTotals(
        members=(*totals.members, counts.member),
        analysed=totals.analysed + (0 if counts.skipped else 1),
        writes=totals.writes + counts.writes,
        covered=totals.covered + counts.covered,
        unhandled=totals.unhandled + counts.unhandled,
        unmodelled=totals.unmodelled + counts.unmodelled,
        skipped=(*totals.skipped, *_skipped(counts)),
        unsettled=(*totals.unsettled, *_unsettled(counts)),
        programs=(*totals.programs, *_seen(counts)),
        aliased=totals.aliased + counts.aliased,
        dead_ends=(*totals.dead_ends, *counts.dead_ends),
        dynamic_sites=totals.dynamic_sites + counts.dynamic_sites,
        resolved_one=totals.resolved_one + counts.resolved_one,
        resolved_several=totals.resolved_several + counts.resolved_several,
        unresolved_reasons=(*totals.unresolved_reasons, *counts.unresolved_reasons),
        file_sites=totals.file_sites + counts.file_sites,
        file_resolved_one=totals.file_resolved_one + counts.file_resolved_one,
        file_resolved_several=(
            totals.file_resolved_several + counts.file_resolved_several
        ),
    )


@dataclass(frozen=True)
class _Sinks:
    """All five artefacts of one run.

    Separate files because only the graph holds flows: which statements could have
    last written a range, which bytes a call site hands to another program, and
    which programs a dynamic call site can reach are all true whether or not
    anything flowed -- and the reason
    targets is its own file is the same reason aliases is: a call site's
    possible callees are not a fact about either program's field graph. See
    side_tables.
    """

    graph: GraphWriter
    defs: JsonlWriter
    aliases: JsonlWriter
    targets: JsonlWriter
    jumps: JsonlWriter

    def add_result(self, result: MemberResult) -> None:
        self.graph.add_all(result.nodes, result.edges)
        self.defs.add_rows(map(defs_row, result.defs))
        self.aliases.add_rows(map(alias_row, result.aliases))
        self.targets.add_rows(map(target_row, result.targets))
        self.jumps.add_rows((jump_identity(j), jump_row(j)) for j in result.jumps)

    def add_member(self, directory: Path) -> None:
        """One finished member's tables, replayed in the order they were written,
        so the writers dedupe across members exactly as one uninterrupted run."""
        tuple(map(self._add_graph_row, read_graph_rows(directory / GRAPH_FILE)))
        self.defs.add_rows(_identified(directory / DEFS_FILE, _defs_identity))
        self.aliases.add_rows(_identified(directory / ALIASES_FILE, _alias_identity))
        self.targets.add_rows(_identified(directory / TARGETS_FILE, _target_identity))
        self.jumps.add_rows(_identified(directory / JUMPS_FILE, _jump_identity))

    def _add_graph_row(self, row: GraphNode | GraphEdge) -> None:
        if isinstance(row, GraphEdge):
            self.graph.add_edge(row)
            return
        self.graph.add_node(row)


def _defs_identity(row: Row) -> str:
    return defs_identity(
        rows.text(row, "program"), rows.text(row, "node"), rows.text(row, "extent")
    )


def _alias_identity(row: Row) -> str:
    return alias_identity(
        rows.text(row, "caller"),
        rows.text(row, "node"),
        rows.text(row, "caller_extent"),
    )


def _target_identity(row: Row) -> str:
    return target_identity(rows.text(row, "caller"), rows.text(row, "node"))


def _jump_identity(row: Row) -> str:
    return "\0".join(
        (rows.text(row, "program"), rows.text(row, "node"), rows.text(row, "kind"))
    )


def _identified(
    path: Path, identity: Callable[[Row], str]
) -> tuple[tuple[str, str], ...]:
    """Each line of a member's table under the identity its writer deduped it on;
    the line itself is kept as written, so the corpus file is the same bytes."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(zip(map(identity, rows.read(path)), lines, strict=True))


def _walk_note(result: MemberCounts) -> str:
    """How the answer was reached, when that changes what it means."""
    if not result.sweeps:
        return (
            ""
            if result.settled
            else ", NOT SETTLED at the dequeue cap -- edges are a subset"
        )
    if result.settled:
        return f", settled in {result.sweeps} sweeps"
    return f", NOT SETTLED after {result.sweeps} sweeps -- edges are a subset"


def _log_result(result: MemberCounts, seconds: float) -> None:
    if result.skipped:
        logger.warning(
            "fields:   %s skipped after %.1fs: %s",
            result.member,
            seconds,
            result.skipped,
        )
        return
    logger.info(
        "fields:   %s %d/%d writes covered, %d unhandled, %d unmodelled, %d edges,"
        " %d of %d extents tracked, %.1fs%s",
        result.program,
        result.covered,
        result.writes,
        result.unhandled,
        result.unmodelled,
        result.edges,
        result.relevant,
        result.tracked,
        seconds,
        _walk_note(result),
    )


@dataclass(frozen=True)
class _MemberTask:
    """What a worker process needs to analyse one member: plain values only."""

    member: str
    path: Path
    block: tuple[Row, ...]
    options: AnalysisOptions
    members: Path
    reused: bool = False
    position: int = 0


@dataclass(frozen=True)
class _Finished:
    """One member's counts back from a worker, and where it sits in table order."""

    position: int
    counts: MemberCounts
    seconds: float
    reused: bool


def _analysed(task: _MemberTask) -> tuple[MemberResult, float]:
    """One member's result and its seconds.

    The layout is built here from the member's table rows rather than shipped
    built: rows are plain values, the layout an object graph many times their size.
    ``CorpusIndex()`` is the same empty index the parent's writer resolves with.
    """
    started = time.monotonic()
    with cached_asg_dialect_parsers_registered():
        result = _member_result(
            member_layout(task.member, task.block),
            task.path,
            task.options,
            CorpusIndex(),
        )
    return result, time.monotonic() - started


def _member_directory(result: MemberResult, members: Path) -> None:
    """Write one member's five tables and counts, then rename the directory into
    place: a member directory that exists is a member that finished."""
    staging = members / f"{result.member}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with (
        graph_writer(staging / GRAPH_FILE, CorpusIndex()) as graph,
        jsonl_writer(staging / DEFS_FILE) as defs,
        jsonl_writer(staging / ALIASES_FILE) as aliases,
        jsonl_writer(staging / TARGETS_FILE) as targets,
        jsonl_writer(staging / JUMPS_FILE) as jumps,
    ):
        _Sinks(graph, defs, aliases, targets, jumps).add_result(result)
    (staging / COUNTS_FILE).write_text(
        counts_of(result).model_dump_json(), encoding="utf-8"
    )
    staging.rename(members / result.member)


def _analysed_in_worker(task: _MemberTask) -> _Finished:
    """A member analysed in a worker process, its directory written there, and
    only its counts sent back. A skipped member gets its directory too: a member
    the walk's budget gave up on still has alias rows, and its counts carry the
    reason, so a resumed run reports the skip exactly as a fresh one."""
    result, seconds = _analysed(task)
    _member_directory(result, task.members)
    return _Finished(task.position, counts_of(result), seconds, reused=False)


def _reused_in_worker(task: _MemberTask) -> _Finished:
    path = task.members / task.member / COUNTS_FILE
    counts = MemberCounts.model_validate_json(path.read_text(encoding="utf-8"))
    return _Finished(task.position, counts, 0.0, reused=True)


_Pending = frozenset[Future[_Finished]]


def _submitted(pool: ProcessPoolExecutor, tasks: Iterator[_MemberTask]) -> _Pending:
    return frozenset(
        pool.submit(_reused_in_worker if task.reused else _analysed_in_worker, task)
        for task in tasks
    )


def _round(
    pool: ProcessPoolExecutor,
    tasks: Iterator[_MemberTask],
    window: int,
    pending: _Pending,
) -> tuple[_Pending, _Pending]:
    """Whatever finished first, and the in-flight set refilled to ``window``."""
    done, running = wait(pending, return_when=FIRST_COMPLETED)
    refill = _submitted(pool, islice(tasks, window - len(running)))
    return frozenset(done), frozenset(running) | refill


def _as_finished(
    pool: ProcessPoolExecutor, tasks: Iterator[_MemberTask], window: int
) -> Iterator[_Finished]:
    """Results as members finish, with at most ``window`` members in flight.

    In completion order, not table order: one slow member at the head of an
    ordered window held every other slot idle behind it -- on a long-tailed corpus,
    most of them for most of the run. The table is still read only ``window``
    members ahead, and nothing downstream needs the order: each worker writes its
    own member directory, and the report is folded in table order afterwards.
    """
    first = _submitted(pool, islice(tasks, window))
    rounds = accumulate(
        repeat(None),
        lambda state, _: _round(pool, tasks, window, state[1]),
        initial=(frozenset(), first),
    )
    return (
        future.result()
        for done, _running in takewhile(lambda state: state[0] or state[1], rounds)
        for future in done
    )


def _reported_member(numbered: tuple[int, _Finished], total: int) -> _Finished:
    """One member's lines, logged as it finishes: ``n`` counts finished members."""
    finished, member = numbered
    if member.reused:
        logger.info("fields: [%d/%d] %s reused", finished, total, member.counts.member)
        return member
    logger.info("fields: [%d/%d] %s", finished, total, member.counts.member)
    _log_result(member.counts, member.seconds)
    return member


def _tasks(inputs: _Inputs) -> Iterator[_MemberTask]:
    """The members the table holds, less the ones this run was not asked for.

    The table drives the run, which is what bounds the memory: a loop over the
    selection would have to ask the file for a member at a time, and a file
    streamed once cannot be asked twice. The order the run reports in is the
    table's.
    """
    selected = (
        (member, block)
        for member, block in member_rows(inputs.extents)
        if member in inputs.chosen
    )
    return (
        _MemberTask(
            member=member,
            path=inputs.chosen[member],
            block=() if reused else block,
            options=inputs.options,
            members=inputs.members,
            reused=reused,
            position=position,
        )
        for position, (member, block) in enumerate(selected)
        for reused in ((inputs.members / member).is_dir(),)
    )


def _unpublished(inputs: _Inputs, totals: RunTotals) -> tuple[MemberCounts, ...]:
    """A reason for every selected member the table never yielded.

    In the order they were asked for, and after the members that were analysed,
    because these were never in the sequence the run followed.
    """
    return tuple(
        MemberCounts(
            member=member,
            skipped=_no_extents(inputs.chosen[member], inputs.extents),
        )
        for member in inputs.chosen
        if member not in totals.members
    )


def _reported(result: MemberCounts) -> MemberCounts:
    """A skip nothing timed, logged the way a timed one is."""
    _log_result(result, 0.0)
    return result


def _run(inputs: _Inputs, pool: ProcessPoolExecutor) -> RunTotals:
    """Every member the table holds that was asked for, then every one it does not.

    The first fold consumes the table once; the second only names what the first
    never saw, and reads no file at all.
    """
    finished = {
        member.position: member.counts
        for member in (
            _reported_member(numbered, len(inputs.chosen))
            for numbered in enumerate(
                _as_finished(pool, _tasks(inputs), inputs.workers), start=1
            )
        )
    }
    reached = reduce(
        _folded, (finished[position] for position in sorted(finished)), RunTotals()
    )
    return reduce(
        lambda totals, result: _folded(totals, _reported(result)),
        _unpublished(inputs, reached),
        reached,
    )


def _exit_code(totals: RunTotals, floor: float) -> int:
    if totals.skipped or _duplicates(totals):
        return 3
    return 0 if totals.coverage >= floor else 1


def _dead_end_note(dead_ends: Sequence[str]) -> str:
    """The second number, which is not the first one's complement.

    Two declarations of one commarea name resolve to two caller cells, and a site
    can share a window through one of them while the other is a zero-length range
    nothing can be crossed through, so the two counts can exceed the site total.
    Neither is distorted to make them sum; the caveat is documented with the counts
    rather than restated on every run that has a dead end.
    """
    counted = ", ".join(
        f"{reason} {count}" for reason, count in _tallied(dead_ends).items()
    )
    if not dead_ends:
        return ""
    return f", {len(dead_ends)} do not: {counted}"


def _report_aliases(totals: RunTotals) -> None:
    """Nothing at all for a run with no call sites: a corpus of leaf programs has
    no alias coverage to state, and a line of zeroes reads as a failure to find
    one. The breakdown is spelled out rather than rendered as a Mapping, whose
    ``%s`` is a Python repr in a report meant to be read."""
    if not totals.aliased and not totals.dead_ends:
        return
    logger.info(
        "fields: %d call sites share a commarea window%s",
        totals.aliased,
        _dead_end_note(totals.dead_ends),
    )


def _target_breakdown(reasons: Sequence[str]) -> str:
    if not reasons:
        return ""
    counted = ", ".join(
        f"{reason} {count}" for reason, count in _tallied(reasons).items()
    )
    return f" ({counted})"


def _report_targets(totals: RunTotals) -> None:
    """Nothing for a run with no dynamic call sites, for the same reason as
    aliases: a corpus of none has no completeness to state. The three buckets
    partition ``dynamic_sites`` -- a site has zero, one or several candidates,
    never two of those at once -- unlike the reason breakdown, which does not."""
    if not totals.dynamic_sites:
        return
    none = totals.dynamic_sites - totals.resolved_one - totals.resolved_several
    logger.info(
        "fields: %d dynamic call sites, %d resolved to one program, %d to "
        "several, %d to none%s",
        totals.dynamic_sites,
        totals.resolved_one,
        totals.resolved_several,
        none,
        _target_breakdown(totals.unresolved_reasons),
    )


def _report_file_sites(totals: RunTotals) -> None:
    """Nothing for a run with no dynamic file sites; the three buckets partition
    ``file_sites`` as the call buckets partition ``dynamic_sites``."""
    if not totals.file_sites:
        return
    none = totals.file_sites - totals.file_resolved_one - totals.file_resolved_several
    logger.info(
        "fields: %d dynamic file sites, %d resolved to one file, %d to several, "
        "%d to none",
        totals.file_sites,
        totals.file_resolved_one,
        totals.file_resolved_several,
        none,
    )


def _report_members(totals: RunTotals) -> None:
    logger.info(
        "fields: %d members, coverage %.1f%% (%d/%d writes), %d unhandled, %d unmodelled, %d skipped",
        totals.analysed,
        totals.coverage * 100,
        totals.covered,
        totals.writes,
        totals.unhandled,
        totals.unmodelled,
        len(totals.skipped),
    )
    _report_aliases(totals)
    _report_targets(totals)
    _report_file_sites(totals)
    for member, reason in sorted(totals.skipped):
        logger.warning("fields: !! skipped %s: %s", member, reason)
    if totals.unsettled:
        logger.warning(
            "fields: !! %d members still growing when their walk's budget ran out "
            "(%s); their edges are a subset of the flows those programs have",
            len(totals.unsettled),
            ", ".join(sorted(totals.unsettled)),
        )


def _report_collisions(totals: RunTotals) -> None:
    for program, members in _duplicates(totals):
        logger.warning(
            "fields: !! program_id %s declared by %d members (%s); "
            "their field nodes share one id namespace",
            program,
            len(members),
            ", ".join(members),
        )


def _report(totals: RunTotals) -> None:
    """The human report on stderr, the machine one on stdout."""
    _report_members(totals)
    _report_collisions(totals)
    json.dump(_summary(totals), sys.stdout)
    sys.stdout.write("\n")


def _writer(
    arguments: argparse.Namespace, locations: CorpusIndex
) -> AbstractContextManager[GraphWriter]:
    return graph_writer(arguments.out_dir / GRAPH_FILE, locations)


def _side_writer(
    arguments: argparse.Namespace, name: str
) -> AbstractContextManager[JsonlWriter]:
    return jsonl_writer(arguments.out_dir / name)


def _selected(asg_dir: Path, members: Sequence[str]) -> tuple[Path, ...]:
    """The named members' cache files, or every one the cache holds.

    Named members keep their given order rather than being sorted. The analysis
    order is the extents table's, since the table is what the run streams, so what
    the given order still decides is which members are analysed at all and the
    order the ones missing from that table are reported in.
    """
    if not members:
        return tuple(sorted(asg_dir.glob("*.json")))
    return tuple(asg_dir / f"{member}.json" for member in members)


def _absent(paths: Sequence[Path]) -> tuple[Path, ...]:
    return tuple(path for path in paths if not path.is_file())


def _scope(arguments: argparse.Namespace) -> Scope:
    if arguments.narrow_areas:
        return Scope.NARROW_CALL_TARGETS
    return Scope.CALL_TARGETS if arguments.call_targets_only else Scope.WHOLE


def _options(arguments: argparse.Namespace) -> AnalysisOptions:
    return AnalysisOptions(
        sweeps=arguments.sweeps,
        factor=arguments.iteration_factor,
        scope=_scope(arguments),
    )


@dataclass(frozen=True)
class _Inputs:
    """What every member of one run is analysed against.

    One value rather than four parameters threaded through four functions: all of
    them are settled before the first member and none of them changes between
    members.
    """

    options: AnalysisOptions
    locations: FileLocationResolver
    extents: Path
    chosen: Mapping[str, Path]
    workers: int
    members: Path


def _inputs(
    paths: Sequence[Path], arguments: argparse.Namespace, locations: CorpusIndex
) -> _Inputs:
    """``chosen`` is the selection by member name, in the order it was given: that
    is the order a member the table does not hold gets reported in."""
    return _Inputs(
        options=_options(arguments),
        locations=locations,
        extents=arguments.extents,
        chosen=MappingProxyType({path.stem: path for path in paths}),
        workers=arguments.max_workers,
        members=arguments.out_dir / MEMBERS_DIR,
    )


def _analysed_run(paths: Sequence[Path], arguments: argparse.Namespace) -> int:
    members = arguments.out_dir / MEMBERS_DIR
    if arguments.force:
        shutil.rmtree(members, ignore_errors=True)
    ensure_dir(members)
    problem = _refusal(arguments, members)
    if problem:
        sys.stderr.write(problem)
        return 2
    return _members_run(paths, arguments)


def _members_run(paths: Sequence[Path], arguments: argparse.Namespace) -> int:
    """One index for both halves: the nodes emit builds and the ones the writer
    synthesises from an edge must carry the same location for the same id.

    ``CorpusIndex()`` holds no mappings, which is honest -- this stage reads the
    ASG cache and never the corpus tree, so it has nothing to index. FIELD
    resolves NOT_INDEXED whatever the index holds; see corpus_index's table.
    """
    locations = CorpusIndex()
    with ProcessPoolExecutor(
        max_workers=arguments.max_workers, initializer=configure_cli_logging
    ) as pool:
        inputs = _inputs(paths, arguments, locations)
        totals = _run(_narrowed(inputs, arguments), pool)
    _publish(arguments, locations, totals)
    _report(totals)
    return _exit_code(totals, arguments.min_coverage)


def _narrowed(inputs: _Inputs, arguments: argparse.Namespace) -> _Inputs:
    """With --narrow-areas, the per-member table cobble-dataflow-area-need wrote,
    handed to every member's walk, which looks up its callees and itself in it."""
    if not arguments.narrow_areas:
        return inputs
    table = table_of(read_rows(Path(arguments.narrow_areas)))
    return replace(inputs, options=replace(inputs.options, areas=table))


def _narrow_problem(arguments: argparse.Namespace) -> str:
    if arguments.narrow_areas and not arguments.call_targets_only:
        return "fields: !! --narrow-areas needs --call-targets-only\n"
    if arguments.narrow_areas:
        return _stored_problem(Path(arguments.narrow_areas))
    return ""


def _stored_problem(path: Path) -> str:
    if not path.is_file():
        return (
            f"fields: !! no area need at {path}: run cobble-dataflow-area-need first\n"
        )
    if not _rows_readable(path):
        return (
            f"fields: !! {path} is not a per-member area need:"
            " rerun cobble-dataflow-area-need\n"
        )
    return ""


def _rows_readable(path: Path) -> bool:
    try:
        read_rows(path)
    except ValidationError:
        return False
    return True


def _refusal(arguments: argparse.Namespace, members: Path) -> str:
    problem = _narrow_problem(arguments)
    if problem:
        return problem
    mixed = _other_scope(members, _options(arguments).scope)
    if mixed:
        return (
            f"fields: !! members analysed in another scope: {', '.join(mixed)};"
            " rerun with --force\n"
        )
    return ""


def _other_scope(members: Path, scope: Scope) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.parent.name
            for path in members.glob(f"*/{COUNTS_FILE}")
            if MemberCounts.model_validate_json(path.read_text(encoding="utf-8")).scope
            is not scope
        )
    )


def _publish(
    arguments: argparse.Namespace, locations: CorpusIndex, totals: RunTotals
) -> None:
    """The four corpus files, rebuilt from every finished member this run reached,
    in table order. Only after every member is done, so an interrupted run leaves
    the previous corpus files as they were rather than half of a new one."""
    finished = tuple(
        directory
        for directory in (arguments.out_dir / MEMBERS_DIR / m for m in totals.members)
        if directory.is_dir()
    )
    with (
        _writer(arguments, locations) as graph,
        _side_writer(arguments, DEFS_FILE) as defs,
        _side_writer(arguments, ALIASES_FILE) as aliases,
        _side_writer(arguments, TARGETS_FILE) as targets,
        _side_writer(arguments, JUMPS_FILE) as jumps,
    ):
        tuple(map(_Sinks(graph, defs, aliases, targets, jumps).add_member, finished))


def _completed(arguments: argparse.Namespace) -> int:
    """A named member the cache does not hold ends the run before it starts.

    Analysing the rest would report a coverage figure over a member set the
    caller did not ask for, and exit 0 while their program went unexamined.
    """
    paths = _selected(arguments.asg_dir, arguments.member)
    absent = _absent(paths)
    if absent:
        logger.error(
            "fields: !! not in the ASG cache: %s",
            ", ".join(path.stem for path in absent),
        )
        return 2
    return _analysed_run(paths, arguments)


def _budget(given: str) -> int:
    """A sweep count below one selects no walk at all, so it is a usage error."""
    count = int(given)
    if count < 1:
        raise argparse.ArgumentTypeError(f"needs at least one sweep, got {count}")
    return count


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--asg-dir",
        type=Path,
        required=True,
        help="the ASG cache cobble-parse-corpus wrote: one JSON per member",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="where this stage's six artefacts go",
    )
    parser.add_argument(
        "--extents",
        type=Path,
        required=True,
        help="extents.jsonl from cobble-extents: the layout this stage reads",
    )


def _add_walk_budget(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-coverage", type=float, default=DEFAULT_FLOOR)
    parser.add_argument(
        "--call-targets-only",
        action="store_true",
        help="track only the bytes call targets and jump areas depend on",
    )
    parser.add_argument(
        "--narrow-areas",
        default="",
        metavar="FILE",
        help="with --call-targets-only: of each handed-over area, track only the bytes"
        " the area need in FILE says some program reads (cobble-dataflow-area-need)",
    )
    walk = parser.add_mutually_exclusive_group()
    walk.add_argument(
        "--iteration-factor",
        type=int,
        default=ITERATION_FACTOR,
        help="dequeues allowed per CFG node before a member is given up on",
    )
    walk.add_argument(
        "--sweeps",
        type=_budget,
        default=0,
        metavar="N",
        help="reverse-postorder passes instead of the worklist; 2 is the useful floor",
    )


def _add_selection(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--member", nargs="+", default=(), metavar="NAME")
    selection.add_argument("--all", action="store_true")


def _add_workers(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        help="discard every finished member under <out-dir>/members and analyse again",
    )
    parser.add_argument(
        "--max-workers",
        type=worker_count,
        default=4,
        help="worker processes analysing members in parallel (default 4)",
    )


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Field-level byte dataflow over a cached ASG corpus."
    )
    _add_inputs(parser)
    _add_walk_budget(parser)
    _add_selection(parser)
    _add_workers(parser)
    return parser.parse_args(tuple(argv) if argv else None)


def _rejected(arguments: argparse.Namespace) -> bool:
    """Whether the run cannot start."""
    return _missing_input(arguments)


def _missing_input(arguments: argparse.Namespace) -> bool:
    """Whether either input is out of reach, said once per input.

    The extents table is as much an input as the cache, and a run that cannot find
    it has nothing to analyse rather than 300 members to skip identically.
    """
    if not arguments.asg_dir.is_dir():
        logger.error("fields: !! no ASG cache at %s", arguments.asg_dir)
        return True
    if not arguments.extents.is_file():
        logger.error(
            "fields: !! no extents table at %s; run cobble-extents --asg-dir %s "
            "--out %s",
            arguments.extents,
            arguments.asg_dir,
            arguments.extents,
        )
        return True
    return False


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parsed(argv)
    if _rejected(arguments):
        return 2
    return _completed(arguments)


def main() -> int:
    sys.exit(cli())
