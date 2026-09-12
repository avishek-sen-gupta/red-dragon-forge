"""The trace as JSONL, streamed to disk one path at a time.

Each path's deps are appended immediately so a killed run still produces a
queryable file. Footer rows (dead ends, coverage, limits) are written once at
the end when the run completes. The file may contain duplicate dep rows across
paths; the query tool deduplicates on load.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Mapping, Sequence
from io import TextIOWrapper
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.trace import (
    DEFAULT_COVERAGE,
    DEFAULT_PATHS,
    Budget,
    DeadEnd,
    Dep,
    Sink,
    Trace,
    loadable,
    sampled_streaming,
)
from cobol_memory.field_extent import FieldExtent, Precision

logger = logging.getLogger(__name__)

LIMITS_ITEMS = (
    "unsampled paths' flows are missing;" " the coverage percentage is the disclosure",
    "a loop body runs once," " so a dependency needing a second iteration is missed",
    "conditions are not evaluated," " so some sampled paths cannot happen at run time",
    'sound one way only: absence means "not sampled",' ' never "does not exist"',
)


def _extent_dict(extent: FieldExtent) -> Mapping[str, str | int | bool]:
    return {
        "field": extent.field_name,
        "region": extent.region.value,
        "start": extent.start,
        "end": extent.start + extent.length,
        "clamped": extent.precision is Precision.CLAMPED,
    }


def _dep_row(dep: Dep) -> str:
    """``source_program`` rides beside ``source`` and appears exactly when it does.

    An extent is addressed by a program, and the two ends of a bridge dep are not
    in the same one, so a single ``program`` cannot address both. A row with an
    origin has no source to address.
    """
    source = _extent_dict(dep.source) if not dep.origin else None
    return json.dumps(
        {
            "kind": "dep",
            "program": dep.program,
            "via": dep.via,
            "target": _extent_dict(dep.target),
            "origin": dep.origin,
            "source": source,
            **({} if dep.origin else {"source_program": dep.source_program}),
            "site": f"{dep.program}/{dep.node}",
            "definers": list(dep.definers),
        },
        separators=(",", ":"),
    )


def _dead_end_row(dead_end: DeadEnd) -> str:
    return json.dumps(
        {
            "kind": "dead_end",
            "program": dead_end.program,
            "node": f"{dead_end.program}/{dead_end.node}",
            "transfer": dead_end.transfer,
            "callee": dead_end.callee,
            "reason": dead_end.reason,
        },
        separators=(",", ":"),
    )


def _coverage_row(trace: Trace) -> str:
    return json.dumps(
        {
            "kind": "coverage",
            "taken": len(trace.coverage.taken),
            "total": trace.coverage.total,
            "paths": trace.paths,
            "programs": len(trace.coverage.programs),
        },
        separators=(",", ":"),
    )


def _limits_row() -> str:
    return json.dumps(
        {"kind": "limits", "items": list(LIMITS_ITEMS)},
        separators=(",", ":"),
    )


def _footer_lines(trace: Trace) -> tuple[str, ...]:
    return (
        *(sorted(_dead_end_row(de) for de in trace.dead_ends)),
        _coverage_row(trace),
        _limits_row(),
    )


def _make_sink(handle: TextIOWrapper) -> Sink:
    def _write_deps(deps: frozenset[Dep]) -> None:
        for dep in sorted(deps, key=lambda d: (d.program, d.node)):
            handle.write(_dep_row(dep) + "\n")
        handle.flush()

    return _write_deps


def _positive(given: str) -> int:
    count = int(given)
    if count < 1:
        raise argparse.ArgumentTypeError(f"needs at least one, got {count}")
    return count


def _fraction(given: str) -> float:
    found = float(given)
    if found <= 0 or found > 1:
        raise argparse.ArgumentTypeError(f"needs a fraction in (0, 1], got {found}")
    return found


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sample concrete paths through one program and the callees it LINKs, "
            "reporting the byte provenance each path witnessed."
        )
    )
    parser.add_argument("program", help="the ASG cache stem to start from")
    parser.add_argument(
        "--asg-dir", required=True, type=Path, help="the parse every stage reads"
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="where to write the JSONL trace",
    )
    parser.add_argument(
        "--paths",
        type=_positive,
        default=DEFAULT_PATHS,
        metavar="N",
        help="paths to sample before stopping",
    )
    parser.add_argument(
        "--coverage",
        type=_fraction,
        default=DEFAULT_COVERAGE,
        metavar="F",
        help="stop once this fraction of branch edges has been taken",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=0,
        metavar="N",
        help="nodes one path may visit (default: 2x the entry program's CFG nodes)",
    )
    return parser


def _refused(asg_dir: Path, program: str) -> str:
    if not asg_dir.is_dir():
        return f"no ASG cache at {asg_dir}"
    return loadable(asg_dir, program)


def _run_trace(program: str, asg_dir: Path, budget: Budget, out: Path) -> Trace:
    logger.info(
        "trace: sampling %s  paths=%d  coverage=%.2f  max_depth=%d",
        program,
        budget.paths,
        budget.coverage,
        budget.max_depth,
    )
    started = time.monotonic()
    with out.open("w", encoding="utf-8") as handle:
        trace = sampled_streaming(program, asg_dir, budget, _make_sink(handle))
        for line in _footer_lines(trace):
            handle.write(line + "\n")
    elapsed = time.monotonic() - started
    logger.info(
        "trace: %d dead ends, %d/%d branches (%.0f%%) over %d paths in %.1fs",
        len(trace.dead_ends),
        len(trace.coverage.taken),
        trace.coverage.total,
        100 * trace.coverage.fraction,
        trace.paths,
        elapsed,
    )
    return trace


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    reason = _refused(arguments.asg_dir, arguments.program)
    if reason:
        logger.error("trace: !! %s", reason)
        return 2
    budget = Budget(
        paths=arguments.paths,
        coverage=arguments.coverage,
        max_depth=arguments.max_depth,
    )
    _run_trace(arguments.program, arguments.asg_dir, budget, arguments.out)
    return 0


def main() -> int:
    sys.exit(cli())
