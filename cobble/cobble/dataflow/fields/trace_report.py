"""The trace as JSONL, streamed to disk one path at a time.

Each path's deps are appended immediately so a killed run still produces a
queryable file. Footer rows (dead ends, coverage, limits) are written once at
the end when the run completes. The file may contain duplicate dep rows across
paths; the query tool deduplicates on load.
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import IO

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
from cobble.path_utils import ensure_parent
from cobol_memory.field_extent import FieldExtent, Precision

logger = logging.getLogger(__name__)

LIMITS_ITEMS = (
    "unsampled paths' flows are missing;" " the coverage percentage is the disclosure",
    "a loop body runs once," " so a dependency needing a second iteration is missed",
    "conditions are not evaluated," " so some sampled paths cannot happen at run time",
    'sound one way only: absence means "not sampled",' ' never "does not exist"',
)


@dataclass(frozen=True)
class _PathRecord:
    path_index: int
    nodes: tuple[str, ...]
    deps: tuple[dict, ...]


def _path_record_row(record: _PathRecord) -> str:
    return json.dumps(
        {
            "kind": "path",
            "path_index": record.path_index,
            "nodes": list(record.nodes),
            "deps": list(record.deps),
        }
    )


def _dep_dict(dep: Dep) -> dict:
    """The dep as a plain dict (for embedding inside path records)."""
    return json.loads(_dep_row(dep))


class _PathRecorder:
    """Accumulates per-path state and writes one path record per completed path.

    ``record_dep`` is called once per Dep as paths are streamed.
    ``flush`` is called once per completed path via PathListener.
    """

    def __init__(
        self,
        path_file: IO[str],
    ) -> None:
        self._path_file = path_file
        self._path_index: int = 0
        self._pending_deps: list[dict] = []

    def record_dep(self, dep: Dep) -> _PathRecorder:
        object.__setattr__(self, "_pending_deps", [*self._pending_deps, _dep_dict(dep)])
        return self

    def flush(
        self,
        nodes: tuple[str, ...],
    ) -> _PathRecorder:
        record = _PathRecord(
            path_index=self._path_index,
            nodes=nodes,
            deps=tuple(self._pending_deps),
        )
        self._path_file.write(_path_record_row(record) + "\n")
        object.__setattr__(self, "_path_index", self._path_index + 1)
        object.__setattr__(self, "_pending_deps", [])
        return self


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
    parser.add_argument(
        "--record-paths",
        type=Path,
        default=None,
        metavar="PATHS",
        help="if given, write one path record per sampled path to this JSONL file",
    )
    return parser


def _refused(asg_dir: Path, program: str) -> str:
    if not asg_dir.is_dir():
        return f"no ASG cache at {asg_dir}"
    return loadable(asg_dir, program)


def _log_start(program: str, budget: Budget) -> float:
    logger.info(
        "trace: sampling %s  paths=%d  coverage=%.2f  max_depth=%d",
        program,
        budget.paths,
        budget.coverage,
        budget.max_depth,
    )
    return time.monotonic()


def _log_done(trace: Trace, started: float) -> None:
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


def _run_trace(program: str, asg_dir: Path, budget: Budget, out: Path) -> Trace:
    started = _log_start(program, budget)
    ensure_parent(out)
    with out.open("w", encoding="utf-8") as handle:
        trace = sampled_streaming(program, asg_dir, budget, _make_sink(handle))
        _write_footer(handle, trace)
    _log_done(trace, started)
    return trace


def _record_deps_for(recorder: _PathRecorder, deps: frozenset[Dep]) -> None:
    for dep in sorted(deps, key=lambda d: d.node):
        recorder.record_dep(dep)


def _path_flush(recorder: _PathRecorder, nodes: tuple[str, ...]) -> None:
    recorder.flush(nodes)


def _make_recording_sink(write_sink: Sink, recorder: _PathRecorder) -> Sink:
    def _combined(deps: frozenset[Dep]) -> None:
        write_sink(deps)
        _record_deps_for(recorder, deps)

    return _combined


def _write_footer(handle: IO[str], trace: Trace) -> None:
    for line in _footer_lines(trace):
        handle.write(line + "\n")


def _stream_with_recorder(
    recorder: _PathRecorder,
    program: str,
    asg_dir: Path,
    budget: Budget,
    out: Path,
) -> Trace:
    with out.open("w", encoding="utf-8") as handle:
        sink = _make_recording_sink(_make_sink(handle), recorder)
        listener = functools.partial(_path_flush, recorder)
        trace = sampled_streaming(program, asg_dir, budget, sink, listener)
        _write_footer(handle, trace)
    return trace


def _run_trace_with_recorder(
    program: str,
    asg_dir: Path,
    budget: Budget,
    out: Path,
    record_paths: Path,
) -> Trace:
    started = _log_start(program, budget)
    ensure_parent(out)
    ensure_parent(record_paths)
    with record_paths.open("w", encoding="utf-8") as paths_handle:
        trace = _stream_with_recorder(
            _PathRecorder(paths_handle), program, asg_dir, budget, out
        )
    _log_done(trace, started)
    return trace


def _budget_from(arguments: argparse.Namespace) -> Budget:
    return Budget(
        paths=arguments.paths,
        coverage=arguments.coverage,
        max_depth=arguments.max_depth,
    )


def _dispatch_trace(arguments: argparse.Namespace, budget: Budget) -> None:
    match arguments.record_paths:
        case None:
            _run_trace(arguments.program, arguments.asg_dir, budget, arguments.out)
        case record_paths:
            _run_trace_with_recorder(
                arguments.program,
                arguments.asg_dir,
                budget,
                arguments.out,
                record_paths,
            )


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    reason = _refused(arguments.asg_dir, arguments.program)
    if reason:
        logger.error("trace: !! %s", reason)
        return 2
    _dispatch_trace(arguments, _budget_from(arguments))
    return 0


def main() -> int:
    sys.exit(cli())
