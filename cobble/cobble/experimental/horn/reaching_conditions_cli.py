"""cobble-experimental-reaching-conditions: the ways one node of one program is reached, each checked by Z3."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.program import Program, program_of
from cobble.experimental.horn.reaching_conditions import (
    CheckedWay,
    Report,
    RouteTest,
    RouteVerdict,
    reaching_conditions,
)
from cobble.experimental.horn.ways import MAX_WAYS, Decision
from cobble.parsing.asg_cache import first_program_at

logger = logging.getLogger(__name__)

SECTIONS = (
    RouteVerdict.EITHER_WAY,
    RouteVerdict.IF_IT_RUNS,
    RouteVerdict.NEVER_RUNS,
    RouteVerdict.GAVE_UP,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-reaching-conditions",
        description=(
            "Experimental: the ways one CFG node is reached, as the tests that decide "
            "each, with every way Z3 proves impossible left out."
        ),
    )
    parser.add_argument("--asg", type=Path, required=True, help="one program's ASG")
    parser.add_argument("--node", required=True, help="a CFG node id")
    return parser


def _ways(count: int) -> str:
    return f"{count} way" if count == 1 else f"{count} ways"


def _test(program: Program, test: str) -> str:
    node = program.cfg.node(test)
    return f"{node.atom.text} ({node.span.line_start})"


def _decision(program: Program, decision: Decision) -> str:
    return f"{_test(program, decision.test)} {decision.outcome.name}"


def _route(
    program: Program, route: tuple[RouteTest, ...], verdict: RouteVerdict
) -> tuple[str, ...]:
    tests = tuple(
        _test(program, t.test)
        + (f" {t.outcome.name}" if t.outcome is not Outcome.UNRUN else "")
        for t in route
        if t.verdict is verdict
    )
    return (f"    {verdict.value}: {', '.join(tests)}",) if tests else ()


def _way(program: Program, index: int, checked: CheckedWay) -> tuple[str, ...]:
    decisions = ", ".join(_decision(program, d) for d in checked.way.decisions)
    gave_up = " (solver gave up)" if checked.answer is Answer.UNKNOWN else ""
    head = f"  way {index}: {decisions or 'no deciding tests'}{gave_up}"
    return (
        head,
        *(
            line
            for verdict in SECTIONS
            for line in _route(program, checked.route, verdict)
        ),
    )


def render(program: Program, report: Report) -> tuple[str, ...]:
    node = program.cfg.node(report.node)
    return (
        f"{report.program} {report.node} ({node.span.line_start}): {_ways(len(report.ways))}",
        *(line for n, way in enumerate(report.ways) for line in _way(program, n, way)),
        *(
            (f"  dropped: {_ways(report.dropped)} Z3 proved impossible",)
            if report.dropped
            else ()
        ),
        *(
            (f"  (cut at {MAX_WAYS} ways: this list is incomplete)",)
            if report.cut
            else ()
        ),
    )


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    with cached_asg_dialect_parsers_registered():
        program = program_of(first_program_at(arguments.asg))
    if arguments.node not in program.cfg.node_ids:
        logger.error("%s is not a node of %s", arguments.node, program.cfg.program)
        return 1
    report = reaching_conditions(program, arguments.node, time.monotonic)
    sys.stdout.write("\n".join(render(program, report)) + "\n")
    return 0
