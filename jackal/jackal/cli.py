"""jackal command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from jackal.jcl.parser import parse_jcl
from jackal.missing_data import LenientAllocation
from jackal.missing_program import StubMissingProgram
from jackal.results import JobResult
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy


def _parse_dataset(spec: str) -> tuple[str, Path]:
    dsn, path = spec.split("=", 1)
    return dsn, Path(path)


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


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jackal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run")
    runp.add_argument("jcl")
    runp.add_argument("--source-dir", default="")
    runp.add_argument("--data-dir", default="")
    runp.add_argument("--copybook-dir", default="")
    runp.add_argument("--dataset", action="append", default=[])
    return ap


def _runner(args: argparse.Namespace, ap: argparse.ArgumentParser) -> JobRunner:
    return JobRunner(
        source_dir=_resolve_dir(args.source_dir, "app/cbl", "--source-dir", ap),
        bridge_jar=os.environ.get("PROLEAP_BRIDGE_JAR", ""),
        data_dir=_resolve_dir(args.data_dir, "app/data/EBCDIC", "--data-dir", ap),
        copybook_dir=_resolve_dir(args.copybook_dir, "app/cpy", "--copybook-dir", ap),
        unresolved=RaiseErrorStrategy(),
        missing_data=LenientAllocation(),
        missing_program=StubMissingProgram(),
    )


def _report(result: JobResult) -> int:
    sys.stdout.write(
        "".join(f"{s.name}: {s.outcome.rendered()}\n" for s in result.steps)
    )
    return 0 if result.outcome.succeeded() else 1


def run(argv: Sequence[str]) -> int:
    ap = _parser()
    args = ap.parse_args(argv)
    runner = _runner(args, ap)
    job = parse_jcl(Path(args.jcl).read_text())
    seeds = dict(_parse_dataset(s) for s in args.dataset)
    with tempfile.TemporaryDirectory(prefix="jackal_") as wd:
        return _report(runner.run(job, workdir=Path(wd), seeds=seeds))


def main() -> int:
    return run(sys.argv[1:])
