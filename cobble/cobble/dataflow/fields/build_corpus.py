"""The field dataflow corpus pass.

No JVM: the ASG cache is the whole input. A member that raises is reported and the
run continues, because the answer wanted from a corpus pass is "which members are
missing from this output", and a run that aborts answers that for one member only.

Four files, so that the graph holds only what nothing outside it could state:

  nodes.jsonl    the FIELD endpoints, no attributes
  edges.jsonl    one FLOWS_TO per (node, source extent, target extent)
  extents.jsonl  every declared name's level, usage, and byte ranges
  defs.jsonl     the definitions reaching each (node, source extent)

The two side tables are relations of their own rather than edge attributes
because both are many-to-one against a flow: one read has as many reaching
definitions as it has paths, and one byte range as many declared names as it has
groups and redefinitions over it. Held on the edge they were duplicated per path
and deduplicated by endpoint, which dropped all but one. ``fields.query`` joins
them back; nothing about a flow is recoverable only from a fan-out.

Intra-program only: a CALL or LINK contributes a synthetic %CALL:<target> source
and no callee summary. Cross-program flow is a separate stage, so naming several
members analyses each one independently -- no edge crosses a program.

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
  2 - ASG directory not found, config missing its table, or a --member the
      cache does not hold
  3 - one or more members skipped, unreadable, or colliding on program_id
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import groupby
from operator import itemgetter
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_index import CorpusIndex, FileLocationResolver
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.config import FieldsConfig, load_fields_config
from cobble.dataflow.fields.emit import graph_records
from cobble.dataflow.fields.fixpoint import analysed
from cobble.dataflow.fields.options import ITERATION_FACTOR, AnalysisOptions
from cobble.dataflow.fields.side_tables import (
    FieldExtents,
    JsonlWriter,
    ReachingDefs,
    defs_row,
    extent_row,
)
from cobble.knowledge_graph.graph_types import GraphEdge, GraphNode
from cobble.knowledge_graph.graph_writer import GraphWriter
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)

NODES_FILE = "nodes.jsonl"
EDGES_FILE = "edges.jsonl"
EXTENTS_FILE = "extents.jsonl"
DEFS_FILE = "defs.jsonl"
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
    extents: tuple[FieldExtents, ...] = ()
    defs: tuple[ReachingDefs, ...] = ()
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    sweeps: int = 0
    settled: bool = True
    skipped: str = ""


@dataclass(frozen=True)
class RunTotals:
    """The run so far. ``programs`` is every (program_id, member) pair seen.

    Pairs rather than a keyed map: a program_id declared by two members is normal
    on a real corpus, and a map keyed by it would keep the last member and lose
    the others without saying so.
    """

    analysed: int = 0
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    skipped: tuple[tuple[str, str], ...] = ()
    unsettled: tuple[str, ...] = ()
    programs: tuple[tuple[str, str], ...] = ()

    @property
    def coverage(self) -> float:
        return self.covered / self.writes if self.writes else 0.0


def _summary(totals: RunTotals) -> dict[str, float | int]:
    return {
        "analysed": totals.analysed,
        "writes": totals.writes,
        "covered": totals.covered,
        "coverage": round(totals.coverage, 4),
        "unhandled": totals.unhandled,
        "skipped": len(totals.skipped),
        "unsettled": len(totals.unsettled),
        "collisions": len(_duplicates(totals)),
    }


def _duplicates(totals: RunTotals) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every program_id more than one member declares, with those members."""
    grouped = groupby(sorted(totals.programs), key=itemgetter(0))
    named = (
        (program, tuple(member for _, member in rows)) for program, rows in grouped
    )
    return tuple((program, members) for program, members in named if len(members) > 1)


def _analysed_member(
    path: Path, options: AnalysisOptions, locations: FileLocationResolver
) -> MemberResult:
    asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
    flow, index = analysed(asg, options)
    if flow.skipped:
        return MemberResult(
            member=path.stem, program=flow.program, skipped=flow.skipped
        )
    records = graph_records(flow, index, locations)
    return MemberResult(
        member=path.stem,
        program=flow.program,
        nodes=records.nodes,
        edges=records.edges,
        extents=records.extents,
        defs=records.defs,
        writes=flow.writes,
        covered=flow.covered,
        unhandled=flow.unhandled,
        sweeps=flow.sweeps,
        settled=flow.settled,
    )


def _member_result(
    path: Path, options: AnalysisOptions, locations: FileLocationResolver
) -> MemberResult:
    """Every failure one member can have, as a reason rather than an abort.

    The records are built before anything is written, so a member that raises
    halfway through leaves no partial rows behind it.
    """
    try:
        return _analysed_member(path, options, locations)
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        return MemberResult(member=path.stem, skipped=f"unreadable: {error!r}")


def _skipped(result: MemberResult) -> tuple[tuple[str, str], ...]:
    return ((result.member, result.skipped),) if result.skipped else ()


def _seen(result: MemberResult) -> tuple[tuple[str, str], ...]:
    return ((result.program, result.member),) if result.program else ()


def _unsettled(result: MemberResult) -> tuple[str, ...]:
    return () if result.skipped or result.settled else (result.member,)


def _folded(totals: RunTotals, result: MemberResult) -> RunTotals:
    return RunTotals(
        analysed=totals.analysed + (0 if result.skipped else 1),
        writes=totals.writes + result.writes,
        covered=totals.covered + result.covered,
        unhandled=totals.unhandled + result.unhandled,
        skipped=(*totals.skipped, *_skipped(result)),
        unsettled=(*totals.unsettled, *_unsettled(result)),
        programs=(*totals.programs, *_seen(result)),
    )


@dataclass(frozen=True)
class _Sinks:
    """All four artefacts of one run.

    Separate files because only two of them are graph facts: where a field is
    declared, and which statements could have last written a range, are both true
    of a program whether or not anything flowed. See side_tables.
    """

    graph: GraphWriter
    extents: JsonlWriter
    defs: JsonlWriter

    def add_result(self, result: MemberResult) -> None:
        self.graph.add_all(result.nodes, result.edges)
        self.extents.add_rows(map(extent_row, result.extents))
        self.defs.add_rows(map(defs_row, result.defs))


def _written(sinks: _Sinks, result: MemberResult) -> MemberResult:
    sinks.add_result(result)
    return result


def _walk_note(result: MemberResult) -> str:
    """How the answer was reached, when that changes what it means."""
    if not result.sweeps:
        return ""
    if result.settled:
        return f", settled in {result.sweeps} sweeps"
    return f", NOT SETTLED after {result.sweeps} sweeps -- edges are a subset"


def _log_result(result: MemberResult, seconds: float) -> None:
    if result.skipped:
        logger.warning(
            "fields:   %s skipped after %.1fs: %s",
            result.member,
            seconds,
            result.skipped,
        )
        return
    logger.info(
        "fields:   %s %d/%d writes covered, %d unhandled, %d edges, %.1fs%s",
        result.program,
        result.covered,
        result.writes,
        result.unhandled,
        len(result.edges),
        seconds,
        _walk_note(result),
    )


def _logged_member(
    numbered: tuple[int, Path],
    total: int,
    options: AnalysisOptions,
    locations: FileLocationResolver,
) -> MemberResult:
    """One member's analysis, announced before it starts and measured after.

    Before, because a member can take minutes: a run that says nothing until it
    finishes is indistinguishable from a hung one.
    """
    position, path = numbered
    logger.info("fields: [%d/%d] %s", position, total, path.stem)
    started = time.monotonic()
    result = _member_result(path, options, locations)
    _log_result(result, time.monotonic() - started)
    return result


def _run(
    sinks: _Sinks,
    paths: Sequence[Path],
    options: AnalysisOptions,
    locations: FileLocationResolver,
) -> RunTotals:
    return reduce(
        lambda totals, numbered: _folded(
            totals,
            _written(sinks, _logged_member(numbered, len(paths), options, locations)),
        ),
        enumerate(paths, start=1),
        RunTotals(),
    )


def _exit_code(totals: RunTotals, floor: float) -> int:
    if totals.skipped or _duplicates(totals):
        return 3
    return 0 if totals.coverage >= floor else 1


def _report_members(totals: RunTotals) -> None:
    logger.info(
        "fields: %d members, coverage %.1f%% (%d/%d writes), %d unhandled, %d skipped",
        totals.analysed,
        totals.coverage * 100,
        totals.covered,
        totals.writes,
        totals.unhandled,
        len(totals.skipped),
    )
    for member, reason in sorted(totals.skipped):
        logger.warning("fields: !! skipped %s: %s", member, reason)
    if totals.unsettled:
        logger.warning(
            "fields: !! %d members still growing when the sweep budget ran out "
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


def _writer(config: FieldsConfig, locations: CorpusIndex) -> GraphWriter:
    return GraphWriter(
        config.out_dir / NODES_FILE, config.out_dir / EDGES_FILE, locations
    )


def _side_writer(config: FieldsConfig, name: str) -> JsonlWriter:
    return JsonlWriter(config.out_dir / name)


def _selected(config: FieldsConfig, members: Sequence[str]) -> tuple[Path, ...]:
    """The named members' cache files, or every one the cache holds.

    Named members keep their given order rather than being sorted: a caller
    naming a program and its callees reads the report in the order they asked.
    """
    if not members:
        return tuple(sorted(config.asg_dir.glob("*.json")))
    return tuple(config.asg_dir / f"{member}.json" for member in members)


def _absent(paths: Sequence[Path]) -> tuple[Path, ...]:
    return tuple(path for path in paths if not path.is_file())


def _options(arguments: argparse.Namespace) -> AnalysisOptions:
    return AnalysisOptions(
        sweeps=arguments.sweeps,
        factor=arguments.iteration_factor,
    )


def _analysed_run(
    config: FieldsConfig, paths: Sequence[Path], arguments: argparse.Namespace
) -> int:
    """One index for both halves: the nodes emit builds and the ones the writer
    synthesises from an edge must carry the same location for the same id.

    ``CorpusIndex()`` holds no mappings, which is honest -- this stage reads the
    ASG cache and never the corpus tree, so it has nothing to index. FIELD
    resolves NOT_INDEXED whatever the index holds; see corpus_index's table.
    """
    config.out_dir.mkdir(parents=True, exist_ok=True)
    locations = CorpusIndex()
    with (
        cached_asg_dialect_parsers_registered(),
        _writer(config, locations) as graph,
        _side_writer(config, EXTENTS_FILE) as extents,
        _side_writer(config, DEFS_FILE) as defs,
    ):
        totals = _run(
            _Sinks(graph, extents, defs), paths, _options(arguments), locations
        )
    _report(totals)
    return _exit_code(totals, arguments.min_coverage)


def _completed(config: FieldsConfig, arguments: argparse.Namespace) -> int:
    """A named member the cache does not hold ends the run before it starts.

    Analysing the rest would report a coverage figure over a member set the
    caller did not ask for, and exit 0 while their program went unexamined.
    """
    paths = _selected(config, arguments.member)
    absent = _absent(paths)
    if absent:
        logger.error(
            "fields: !! not in the ASG cache: %s",
            ", ".join(path.stem for path in absent),
        )
        return 2
    return _analysed_run(config, paths, arguments)


def _budget(given: str) -> int:
    """A sweep count below one selects no walk at all, so it is a usage error."""
    count = int(given)
    if count < 1:
        raise argparse.ArgumentTypeError(f"needs at least one sweep, got {count}")
    return count


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Field-level byte dataflow over a cached ASG corpus."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--min-coverage", type=float, default=DEFAULT_FLOOR)
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
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--member", nargs="+", default=(), metavar="NAME")
    selection.add_argument("--all", action="store_true")
    return parser.parse_args(tuple(argv) if argv else None)


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parsed(argv)
    try:
        config = load_fields_config(arguments.config)
    except (OSError, KeyError, ValueError) as error:
        logger.error("fields: !! %s", error)
        return 2
    if not config.asg_dir.is_dir():
        logger.error("fields: !! no ASG cache at %s", config.asg_dir)
        return 2
    return _completed(config, arguments)


def main() -> int:
    sys.exit(cli())
