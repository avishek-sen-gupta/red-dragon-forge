"""The field dataflow corpus pass.

No JVM: the ASG cache is the whole input. A member that raises is reported and the
run continues, because the answer wanted from a corpus pass is "which members are
missing from this output", and a run that aborts answers that for one member only.

Intra-program only: a CALL or LINK contributes a synthetic %CALL:<target> source
and no callee summary. Cross-program flow is a separate stage, so naming several
members analyses each one independently -- no edge crosses a program.

Exactly one of --member and --all is required. The usual question is about the
fields of one program, so a whole-cache pass is asked for rather than defaulted
into: a run nobody meant to start is minutes of fixpoint per member.

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
from cobble.dataflow.fields.fixpoint import ITERATION_FACTOR, analysed
from cobble.knowledge_graph.graph_types import GraphEdge, GraphNode
from cobble.knowledge_graph.graph_writer import GraphWriter
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)

NODES_FILE = "nodes.jsonl"
EDGES_FILE = "edges.jsonl"
DEFAULT_FLOOR = 0.60


@dataclass(frozen=True)
class AnalysisOptions:
    """What the caller chose about how each member is analysed.

    One value object rather than two parameters threaded through four call
    layers: the next knob belongs here, not in every signature between the CLI
    and the fixpoint.
    """

    expand: bool = False
    factor: int = ITERATION_FACTOR


@dataclass(frozen=True)
class MemberResult:
    """One member's records and counters, or the reason it produced none."""

    member: str
    program: str = ""
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
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
    flow, index = analysed(asg, options.factor)
    if flow.skipped:
        return MemberResult(
            member=path.stem, program=flow.program, skipped=flow.skipped
        )
    nodes, edges = graph_records(flow, index, options.expand, locations)
    return MemberResult(
        member=path.stem,
        program=flow.program,
        nodes=nodes,
        edges=edges,
        writes=flow.writes,
        covered=flow.covered,
        unhandled=flow.unhandled,
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


def _folded(totals: RunTotals, result: MemberResult) -> RunTotals:
    return RunTotals(
        analysed=totals.analysed + (0 if result.skipped else 1),
        writes=totals.writes + result.writes,
        covered=totals.covered + result.covered,
        unhandled=totals.unhandled + result.unhandled,
        skipped=(*totals.skipped, *_skipped(result)),
        programs=(*totals.programs, *_seen(result)),
    )


def _written(writer: GraphWriter, result: MemberResult) -> MemberResult:
    writer.add_all(result.nodes, result.edges)
    return result


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
        "fields:   %s %d/%d writes covered, %d unhandled, %d edges, %.1fs",
        result.program,
        result.covered,
        result.writes,
        result.unhandled,
        len(result.edges),
        seconds,
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
    writer: GraphWriter,
    paths: Sequence[Path],
    options: AnalysisOptions,
    locations: FileLocationResolver,
) -> RunTotals:
    return reduce(
        lambda totals, numbered: _folded(
            totals,
            _written(writer, _logged_member(numbered, len(paths), options, locations)),
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
    return AnalysisOptions(expand=arguments.expand, factor=arguments.iteration_factor)


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
    with cached_asg_dialect_parsers_registered(), _writer(config, locations) as writer:
        totals = _run(writer, paths, _options(arguments), locations)
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


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Field-level byte dataflow over a cached ASG corpus."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--min-coverage", type=float, default=DEFAULT_FLOOR)
    parser.add_argument("--expand", action="store_true")
    parser.add_argument(
        "--iteration-factor",
        type=int,
        default=ITERATION_FACTOR,
        help="dequeues allowed per CFG node before a member is given up on",
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
