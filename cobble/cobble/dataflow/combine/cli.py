"""cobble-dataflow-combine — link the per-program fixpoint results across programs."""

import argparse
import logging
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from cics.csd_parse import parse_csd
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.dataflow.combine.asg_callee_areas import AsgCalleeAreas
from cobble.dataflow.combine.call_groups import call_groups
from cobble.dataflow.combine.link import UNLIMITED_HOPS, link
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.memo_resolve import MemoResolve
from cobble.dataflow.combine.outputs import write_outputs
from cobble.dataflow.combine.outside import outside_jumps
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolve import step
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.combine.table_callee_areas import TableCalleeAreas

_LOG = logging.getLogger(__name__)
_PROGRESS = logging.getLogger(f"{__name__}.progress")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Link the fixpoint's per-program results across programs."
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="the corpus TOML (csd_files, asg_dir)",
    )
    parser.add_argument(
        "--fixpoint-dir",
        required=True,
        type=Path,
        help="a cobble-dataflow-fixpoint --out-dir",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="where targets.jsonl and links.jsonl go",
    )
    parser.add_argument(
        "--max-hops",
        type=_hops,
        default=UNLIMITED_HOPS,
        metavar="N",
        help="program crossings a walk may make; one that would cross more stops "
        "and its target says hop-limit. Default: no limit",
    )
    parser.add_argument(
        "--skip-readbacks",
        action="store_true",
        help="do not walk into a LINKed program for bytes it may have written back; "
        "those bytes say readback-skipped",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--all", action="store_true", help="link every program with results"
    )
    scope.add_argument(
        "--member",
        nargs="+",
        default=[],
        metavar="NAME",
        help="link these programs only",
    )
    return parser


def _hops(text: str) -> int:
    """A negative crossing count limits nothing a walk can do, so it is a usage error."""
    count = int(text)
    if count < 0:
        raise argparse.ArgumentTypeError(f"needs zero or more hops, got {count}")
    return count


def _transactions(csd_files: Sequence[Path]) -> Mapping[str, str]:
    return {
        transid: program
        for path in csd_files
        for transid, program in parse_csd(path).items()
    }


def _inside(
    fixpoint_dir: Path, members: Sequence[str], every: bool
) -> tuple[frozenset[str], tuple[str, ...]]:
    present = frozenset(
        p.name for p in (fixpoint_dir / "members").iterdir() if p.is_dir()
    )
    if every:
        return present, ()
    wanted = frozenset(name.upper() for name in members)
    return wanted & present, tuple(sorted(wanted - present))


def _report(reports: Sequence[RunReport], every: bool) -> None:
    report = _summed(reports)
    _LOG.info(
        "combine: %d rounds, %d discovered edges",
        report.rounds,
        report.discovered,
    )
    if report.crossed:
        _LOG.info("combine: links that crossed call groups: %d", report.crossed)
    if every:
        return
    _LOG.info(
        "combine: %d outside jumps with unresolved targets, "
        "%d outside programs without results",
        report.unresolved_outside_jumps,
        len(report.without_results),
    )


def _summed(reports: Sequence[RunReport]) -> RunReport:
    """Rounds are the most any group took; the outside is the same for every
    group, since it is computed once over the whole selection."""
    first = reports[0] if reports else RunReport()
    return replace(
        first,
        rounds=max((r.rounds for r in reports), default=0),
        discovered=sum(r.discovered for r in reports),
        crossed=sum(r.crossed for r in reports),
    )


def _outside(
    arguments: argparse.Namespace,
    config: CorpusConfig,
    inside: frozenset[str],
    transactions: Mapping[str, str],
) -> OutsideJumps:
    if arguments.all:
        return OutsideJumps()
    return outside_jumps(arguments.fixpoint_dir, config.asg_dir, inside, transactions)


def _load_one(fixpoint_dir: Path, program: str, n: int, total: int) -> ProgramTables:
    tables = load_tables(fixpoint_dir, program)
    _PROGRESS.info(
        "combine:   [%d/%d] %s (%d jumps, %d sites)",
        n,
        total,
        program,
        len(tables.jumps),
        len(tables.sites),
    )
    return tables


def _load_all(
    fixpoint_dir: Path,
    inside: frozenset[str],
) -> Mapping[str, ProgramTables]:
    _PROGRESS.info("combine: loading %d programs", len(inside))
    started = time.monotonic()
    programs = sorted(inside)
    tables = {
        program: _load_one(fixpoint_dir, program, n, len(programs))
        for n, program in enumerate(programs, 1)
    }
    _PROGRESS.info("combine: loaded in %.1fs", time.monotonic() - started)
    return tables


def _crossings(linked: Linked, group: frozenset[str], inside: frozenset[str]) -> int:
    """Links into a program of another group: an edge the grouping missed, whose
    callee's own group was linked without this caller."""
    crossing = sorted(
        {
            (edge.caller, edge.node, edge.callee)
            for edge in linked.edges
            if edge.callee in inside and edge.callee not in group
        }
    )
    tuple(
        _LOG.warning(
            "combine: !! %s %s links to %s, outside its call group",
            caller,
            node,
            callee,
        )
        for caller, node, callee in crossing
    )
    return len(crossing)


def _linked_group(
    arguments: argparse.Namespace,
    config: CorpusConfig,
    group: frozenset[str],
    transactions: Mapping[str, str],
    outside: OutsideJumps,
) -> Linked:
    started = time.monotonic()
    tables = _load_all(arguments.fixpoint_dir, group)
    linked = link(
        tables,
        TableCalleeAreas(tables, AsgCalleeAreas(config.asg_dir)),
        transactions,
        outside,
        MemoResolve(tables, step),
        arguments.max_hops,
        not arguments.skip_readbacks,
    )
    _PROGRESS.info(
        "combine: linked %d programs in %.1fs: %d targets, %d edges",
        len(group),
        time.monotonic() - started,
        len(linked.targets),
        len(linked.edges),
    )
    return linked


def _linked_groups(
    arguments: argparse.Namespace,
    config: CorpusConfig,
    inside: frozenset[str],
    transactions: Mapping[str, str],
) -> Iterator[Linked]:
    groups = call_groups(arguments.fixpoint_dir, inside, transactions)
    _PROGRESS.info(
        "combine: %d call groups, the largest %d programs",
        len(groups),
        max(map(len, groups), default=0),
    )
    outside = _outside(arguments, config, inside, transactions)
    return (
        replace(
            linked,
            report=replace(linked.report, crossed=_crossings(linked, group, inside)),
        )
        for group in groups
        for linked in (_linked_group(arguments, config, group, transactions, outside),)
    )


def _combine(
    arguments: argparse.Namespace, config: CorpusConfig, inside: frozenset[str]
) -> None:
    transactions = _transactions(config.csd_files)
    _PROGRESS.info("combine: %d transactions from CSD", len(transactions))
    reports = write_outputs(
        arguments.out_dir, _linked_groups(arguments, config, inside, transactions)
    )
    _PROGRESS.info("combine: wrote %s", arguments.out_dir)
    _report(reports, arguments.all)


def _unusable(arguments: argparse.Namespace, config: CorpusConfig) -> Sequence[str]:
    members = arguments.fixpoint_dir / "members"
    return (
        *(() if members.is_dir() else (f"no fixpoint results at {members}",)),
        *(() if config.asg_dir.is_dir() else (f"no parse cache at {config.asg_dir}",)),
    )


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(argv or sys.argv[1:])
    if not arguments.config.is_file():
        _LOG.error("combine: !! no corpus config at %s", arguments.config)
        return 2
    return _configured(arguments, load_corpus_config(arguments.config))


def _configured(arguments: argparse.Namespace, config: CorpusConfig) -> int:
    unusable = _unusable(arguments, config)
    if unusable:
        _LOG.error("combine: !! %s", "; ".join(unusable))
        return 2
    inside, missing = _inside(arguments.fixpoint_dir, arguments.member, arguments.all)
    if missing:
        _LOG.error("combine: !! no fixpoint results for: %s", ", ".join(missing))
        return 1
    _combine(arguments, config, inside)
    return 0


def main() -> int:
    sys.exit(cli())
