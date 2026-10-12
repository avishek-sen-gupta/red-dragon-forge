"""jackal command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.labels import RecordFormat, SequentialLabel
from jackal.missing_data import LenientAllocation
from jackal.missing_program import StubMissingProgram
from jackal.model import ProgramRef
from jackal.program_sources import LinkedProgramNotFound
from jackal.results import JobResult
from jackal.runner import JobRunner
from jackal.system_catalog import SystemCatalog
from jackal.unresolved import RaiseErrorStrategy


def _resolve_dir(
    flag_value: str,
    env_subpath: str,
    flag_name: str,
    parser: argparse.ArgumentParser,
) -> Path:
    if flag_value:
        return Path(flag_value)
    carddemo_home = os.environ.get("CARDDEMO_HOME", "")
    if carddemo_home:
        return Path(carddemo_home) / env_subpath
    parser.error(f"{flag_name} is required: supply the flag or set $CARDDEMO_HOME")


def _run_command(runp: argparse.ArgumentParser) -> None:
    runp.add_argument("jcl")
    runp.add_argument("--system", required=True)
    runp.add_argument("--source-dir", default="")
    runp.add_argument("--copybook-dir", default="")
    runp.add_argument("--link", nargs="+", default=[], metavar="PGM")


def _catalog_add_command(add: argparse.ArgumentParser) -> None:
    add.add_argument("dsn")
    add.add_argument("--system", required=True)
    add.add_argument("--file", required=True)
    add.add_argument("--recfm", required=True, choices=[f.value for f in RecordFormat])
    add.add_argument("--lrecl", required=True, type=int)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jackal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _run_command(sub.add_parser("run"))
    catalog = sub.add_parser("catalog").add_subparsers(dest="action", required=True)
    _catalog_add_command(catalog.add_parser("add"))
    return ap


def _runner(args: argparse.Namespace, ap: argparse.ArgumentParser) -> JobRunner:
    try:
        return _job_runner(args, ap)
    except LinkedProgramNotFound as missing:
        ap.error(f"--link: {missing}")


def _job_runner(args: argparse.Namespace, ap: argparse.ArgumentParser) -> JobRunner:
    return JobRunner(
        source_dir=_resolve_dir(args.source_dir, "app/cbl", "--source-dir", ap),
        bridge_jar=os.environ.get("PROLEAP_BRIDGE_JAR", ""),
        system=SystemCatalog(Path(args.system)),
        copybook_dir=_resolve_dir(args.copybook_dir, "app/cpy", "--copybook-dir", ap),
        unresolved=RaiseErrorStrategy(),
        missing_data=LenientAllocation(),
        missing_program=StubMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        linked_programs=tuple(ProgramRef(name) for name in args.link),
    )


def _report(result: JobResult) -> int:
    sys.stdout.write(
        "".join(f"{s.name}: {s.outcome.rendered()}\n" for s in result.steps)
    )
    return 0 if result.outcome.succeeded() else 1


def _run_job(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    runner = _runner(args, ap)
    job = parse_jcl(Path(args.jcl).read_text())
    with tempfile.TemporaryDirectory(prefix="jackal_") as scratch:
        return _report(runner.run(job, scratch=Path(scratch)))


def _catalog_add(args: argparse.Namespace) -> int:
    SystemCatalog(Path(args.system)).add(
        args.dsn,
        Path(args.file),
        SequentialLabel(RecordFormat(args.recfm), args.lrecl),
    )
    return 0


def run(argv: Sequence[str]) -> int:
    ap = _parser()
    args = ap.parse_args(argv)
    if args.cmd == "catalog":
        return _catalog_add(args)
    return _run_job(args, ap)


def main() -> int:
    return run(sys.argv[1:])
