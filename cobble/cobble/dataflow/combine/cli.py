"""cobble-dataflow-combine — link the per-program fixpoint results across programs."""

import argparse
import logging
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from cics.csd_parse import parse_csd
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.dataflow.combine.asg_callee_areas import AsgCalleeAreas
from cobble.dataflow.combine.link import link
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.memo_resolve import MemoResolve
from cobble.dataflow.combine.outputs import write_outputs
from cobble.dataflow.combine.outside import outside_jumps
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolve import resolve
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.combine.table_callee_areas import TableCalleeAreas

_LOG = logging.getLogger(__name__)


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


def _report(report: RunReport, every: bool) -> None:
    _LOG.info(
        "combine: %d rounds, %d discovered edges",
        report.rounds,
        report.discovered,
    )
    if every:
        return
    _LOG.info(
        "combine: %d outside jumps with unresolved targets, "
        "%d outside programs without results",
        report.unresolved_outside_jumps,
        len(report.without_results),
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
    _LOG.info(
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
    _LOG.info("combine: loading %d programs", len(inside))
    started = time.monotonic()
    programs = sorted(inside)
    tables = {
        program: _load_one(fixpoint_dir, program, n, len(programs))
        for n, program in enumerate(programs, 1)
    }
    _LOG.info("combine: loaded in %.1fs", time.monotonic() - started)
    return tables


def _link_and_write(
    arguments: argparse.Namespace,
    config: CorpusConfig,
    tables: Mapping[str, ProgramTables],
    transactions: Mapping[str, str],
    inside: frozenset[str],
) -> Linked:
    started = time.monotonic()
    linked = link(
        tables,
        TableCalleeAreas(tables, AsgCalleeAreas(config.asg_dir)),
        transactions,
        _outside(arguments, config, inside, transactions),
        MemoResolve(tables, resolve),
    )
    _LOG.info("combine: linked in %.1fs", time.monotonic() - started)
    write_outputs(arguments.out_dir, linked)
    _LOG.info(
        "combine: wrote %d targets, %d edges to %s",
        len(linked.targets),
        len(linked.edges),
        arguments.out_dir,
    )
    return linked


def _combine(
    arguments: argparse.Namespace, config: CorpusConfig, inside: frozenset[str]
) -> None:
    transactions = _transactions(config.csd_files)
    _LOG.info("combine: %d transactions from CSD", len(transactions))
    tables = _load_all(arguments.fixpoint_dir, inside)
    linked = _link_and_write(arguments, config, tables, transactions, inside)
    _report(linked.report, arguments.all)


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
