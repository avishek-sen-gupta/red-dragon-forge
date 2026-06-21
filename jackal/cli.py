"""jackal command-line entry point."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from jackal.jcl.parser import parse_jcl
from jackal.runner import JobRunner


def _parse_dataset(spec: str) -> tuple[str, Path]:
    dsn, path = spec.split("=", 1)
    return dsn, Path(path)


def _resolve_dir(
    flag_value: str | None,
    env_subpath: str,
    flag_name: str,
    parser: argparse.ArgumentParser,
) -> Path:
    """Return a concrete Path: flag > $CARDDEMO_HOME/<subpath> > fail loud."""
    if flag_value is not None:
        return Path(flag_value)
    carddemo_home = os.environ.get("CARDDEMO_HOME")
    if carddemo_home:
        return Path(carddemo_home) / env_subpath
    parser.error(f"{flag_name} is required: supply the flag or set $CARDDEMO_HOME")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jackal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run")
    runp.add_argument("jcl")
    runp.add_argument("--source-dir", default=None)
    runp.add_argument("--data-dir", default=None)
    runp.add_argument("--copybook-dir", default=None)
    runp.add_argument("--dataset", action="append", default=[])
    args = ap.parse_args(argv)

    source_dir = _resolve_dir(args.source_dir, "app/cbl", "--source-dir", ap)
    data_dir = _resolve_dir(args.data_dir, "app/data/EBCDIC", "--data-dir", ap)
    copybook_dir = _resolve_dir(args.copybook_dir, "app/cpy", "--copybook-dir", ap)

    job = parse_jcl(Path(args.jcl).read_text())
    seeds = dict(_parse_dataset(s) for s in args.dataset)
    runner = JobRunner(
        source_dir=source_dir,
        bridge_jar=os.environ.get("PROLEAP_BRIDGE_JAR", ""),
        data_dir=data_dir,
        copybook_dir=copybook_dir,
    )
    workdir = Path(tempfile.mkdtemp(prefix="jackal_"))
    result = runner.run(job, workdir=workdir, seeds=seeds)
    for s in result.steps:
        print(f"{s.name}: RC={s.return_code} ran={s.ran}")
    return 0 if all(s.return_code == 0 for s in result.steps) else 1
