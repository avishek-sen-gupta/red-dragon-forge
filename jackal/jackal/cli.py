"""jackal command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from catnip.labels import RecordFormat, SequentialLabel
from catnip.system_catalog import SystemCatalog
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import LenientAllocation
from jackal.missing_program import StubMissingProgram
from jackal.model import Job
from jackal.results import JobResult
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy, UnresolvedReference
from litter.open import open_package
from litter.package import Package
from litter.package_error import PackageError


def _proclibs(flag_values: Sequence[str]) -> tuple[Path, ...]:
    if flag_values:
        return tuple(map(Path, flag_values))
    carddemo_home = os.environ.get("CARDDEMO_HOME", "")
    if carddemo_home:
        return (Path(carddemo_home) / "app/proc",)
    return ()


def _run_command(runp: argparse.ArgumentParser) -> None:
    runp.add_argument("jcl")
    runp.add_argument("--system", required=True)
    runp.add_argument("--package", required=True, metavar="ZIP")
    runp.add_argument("--proclib", action="append", default=[], metavar="DIR")


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


def _package(ap: argparse.ArgumentParser, path: Path) -> Package:
    try:
        return open_package(path)
    except (OSError, zipfile.BadZipFile, PackageError) as unopened:
        ap.error(f"--package {path}: {unopened}")


def _runner(ap: argparse.ArgumentParser, args: argparse.Namespace) -> JobRunner:
    return JobRunner(
        package=_package(ap, Path(args.package)),
        system=SystemCatalog(Path(args.system)),
        unresolved=RaiseErrorStrategy(),
        missing_data=LenientAllocation(),
        missing_program=StubMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        proclib_dirs=_proclibs(args.proclib),
    )


def report(result: JobResult) -> int:
    sys.stdout.write(
        "".join(f"{s.name}: {s.outcome.rendered()}\n" for s in result.steps)
    )
    return 0 if result.outcome.succeeded() else 1


def _run_job(ap: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    runner = _runner(ap, args)
    job = parse_jcl(Path(args.jcl).read_text())
    with tempfile.TemporaryDirectory(prefix="jackal_") as scratch:
        return report(_ran(runner, job, Path(scratch)))


def _ran(runner: JobRunner, job: Job, scratch: Path) -> JobResult:
    try:
        return runner.run(job, scratch=scratch)
    except UnresolvedReference as unresolved:
        sys.stderr.write(f"jackal: {unresolved}\n")
        raise SystemExit(1) from unresolved


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
    return _run_job(ap, args)


def main() -> int:
    return run(sys.argv[1:])
