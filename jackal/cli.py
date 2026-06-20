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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jackal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run")
    runp.add_argument("jcl")
    runp.add_argument("--source-dir", required=True)
    runp.add_argument("--dataset", action="append", default=[])
    args = ap.parse_args(argv)

    job = parse_jcl(Path(args.jcl).read_text())
    seeds = dict(_parse_dataset(s) for s in args.dataset)
    runner = JobRunner(
        source_dir=Path(args.source_dir),
        bridge_jar=os.environ.get("PROLEAP_BRIDGE_JAR", ""),
    )
    workdir = Path(tempfile.mkdtemp(prefix="jackal_"))
    result = runner.run(job, workdir=workdir, seeds=seeds)
    for s in result.steps:
        print(f"{s.name}: RC={s.return_code} ran={s.ran}")
    return 0 if all(s.return_code == 0 for s in result.steps) else 1
