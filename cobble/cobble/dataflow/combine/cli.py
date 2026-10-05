"""cobble-dataflow-combine — link the per-program fixpoint results across programs."""

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from cics.csd_parse import parse_csd
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.dataflow.combine.asg_callee_areas import AsgCalleeAreas
from cobble.dataflow.combine.link import link
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.outputs import write_outputs
from cobble.dataflow.combine.outside import outside_jumps
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.run_report import RunReport


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


def _report(report: RunReport) -> None:
    sys.stderr.write(
        f"combine: {report.rounds} rounds, {report.discovered} discovered edges, "
        f"{report.unresolved_outside_jumps} outside jumps with unresolved targets, "
        f"{len(report.without_results)} outside programs without results\n"
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


def _combine(arguments: argparse.Namespace, inside: frozenset[str]) -> None:
    config = load_corpus_config(arguments.config)
    transactions = _transactions(config.csd_files)
    linked = link(
        {
            program: load_tables(arguments.fixpoint_dir, program)
            for program in sorted(inside)
        },
        AsgCalleeAreas(config.asg_dir),
        transactions,
        _outside(arguments, config, inside, transactions),
    )
    write_outputs(arguments.out_dir, linked)
    _report(linked.report)


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(argv or sys.argv[1:])
    inside, missing = _inside(arguments.fixpoint_dir, arguments.member, arguments.all)
    if missing:
        sys.stderr.write(f"combine: !! no fixpoint results for: {', '.join(missing)}\n")
        return 1
    _combine(arguments, inside)
    return 0


def main() -> int:
    sys.exit(cli())
