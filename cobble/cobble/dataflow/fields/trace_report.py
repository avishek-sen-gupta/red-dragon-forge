"""The trace as text, and the CLI that writes it.

Separate from ``trace.py`` because ``query.py`` in this same directory is the
counter-example: it reached a thousand lines by holding a walk and its output
format together. The walk knows nothing about text; this knows nothing about
paths.

The limits are printed, not only documented. The query-time stop layer was
deleted on 2026-09-07 for being unreadable, and what replaced it is a number a
reader can act on -- so a coverage percentage and four sentences go in the file,
where someone reading an answer will actually meet them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.trace import (
    DEFAULT_COVERAGE,
    DEFAULT_MAX_DEPTH,
    DEFAULT_PATHS,
    Budget,
    Dep,
    Trace,
    loadable,
    sampled,
)

LIMITS = (
    "",
    "limits:",
    "  - unsampled paths' flows are missing; the coverage percentage is the disclosure",
    "  - a loop body runs once, so a dependency needing a second iteration is missed",
    "  - conditions are not evaluated, so some sampled paths cannot happen at run time",
    '  - sound one way only: absence means "not sampled", never "does not exist"',
)


def _group_of(dep: Dep) -> tuple[str, str]:
    return (dep.program, dep.via)


def _came_from(dep: Dep) -> str:
    """An origin where the source is not storage, so an external value reads as
    itself rather than as an absence."""
    return dep.origin if dep.origin else extent_text(dep.source)


def _dep_line(dep: Dep, width: int) -> str:
    """Where these bytes came from, at which statement, and who last wrote them.

    ``defined at`` is the payload. The node is program-qualified, so a definer that
    crossed a call names the member it is in -- the interprocedural chain that a
    query over the intra-program artefacts has to rebuild.
    """
    said = f"    <- {_came_from(dep).ljust(width)}   at {dep.program}/{dep.node}"
    if not dep.definers:
        return f"{said}   (read before write)" if not dep.origin else said
    return f"{said}   defined at {', '.join(dep.definers)}"


def _target_lines(target: str, deps: Sequence[Dep]) -> tuple[str, ...]:
    width = max(len(_came_from(one)) for one in deps)
    return (f"  {target}", *sorted(_dep_line(one, width) for one in deps))


def _group_lines(group: tuple[str, str], deps: Sequence[Dep]) -> tuple[str, ...]:
    program, via = group
    targets = tuple(dict.fromkeys(sorted(extent_text(one.target) for one in deps)))
    return (
        f"{program}   via {via}" if via else program,
        *(
            line
            for target in targets
            for line in _target_lines(
                target, tuple(one for one in deps if extent_text(one.target) == target)
            )
        ),
        "",
    )


def _dependency_lines(trace: Trace) -> tuple[str, ...]:
    if not trace.deps:
        return ("(nothing witnessed on any sampled path)", "")
    groups = tuple(dict.fromkeys(sorted(_group_of(one) for one in trace.deps)))
    return tuple(
        line
        for group in groups
        for line in _group_lines(
            group, tuple(one for one in trace.deps if _group_of(one) == group)
        )
    )


def _dead_end_lines(trace: Trace) -> tuple[str, ...]:
    """Their own section. A site the path could not cross is not a dependency, and
    mixing the two would make an absence read like a finding."""
    if not trace.dead_ends:
        return ("dead ends:", "  (none)", "")
    return (
        "dead ends:",
        *sorted(
            f"  {one.program}/{one.node}   {one.transfer}   "
            f"{one.callee if one.callee else '(unresolved)'}   {one.reason}"
            for one in trace.dead_ends
        ),
        "",
    )


def _summary_lines(trace: Trace) -> tuple[str, ...]:
    found = trace.coverage
    path_word = "path" if trace.paths == 1 else "paths"
    program_word = "program" if len(found.programs) == 1 else "programs"
    return (
        (
            f"branch coverage: {len(found.taken)}/{found.total} "
            f"({round(100 * found.fraction)}%) over {trace.paths} {path_word}, "
            f"{len(found.programs)} {program_word} entered"
        ),
    )


def lines(trace: Trace) -> tuple[str, ...]:
    return (
        *_dependency_lines(trace),
        *_dead_end_lines(trace),
        *_summary_lines(trace),
        *LIMITS,
    )


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
        help="where to write the report; a whole-memory answer is a file, not a terminal",
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
        type=_positive,
        default=DEFAULT_MAX_DEPTH,
        metavar="N",
        help="nodes one path may run before it is cut short",
    )
    return parser


def cli(argv: Sequence[str] = ()) -> int:
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    if not arguments.asg_dir.is_dir():
        sys.stderr.write(f"trace: !! no ASG cache at {arguments.asg_dir}\n")
        return 2
    refused = loadable(arguments.asg_dir, arguments.program)
    if refused:
        sys.stderr.write(f"trace: !! cannot trace {arguments.program}: {refused}\n")
        return 2
    trace = sampled(
        arguments.program,
        arguments.asg_dir,
        Budget(
            paths=arguments.paths,
            coverage=arguments.coverage,
            max_depth=arguments.max_depth,
        ),
    )
    arguments.out.write_text("\n".join(lines(trace)) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    sys.exit(cli())
