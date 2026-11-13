import json
import logging
from pathlib import Path

import pytest
from cobble.dataflow.srccfg.cfg import NodeKind
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.reaching_conditions import (
    CheckedWay,
    Report,
    RouteTest,
    RouteVerdict,
)
from cobble.experimental.horn.reaching_conditions_cli import main, render
from cobble.experimental.horn.ways import Decision, Way
from tests.experimental.horn.asg_builder import FIELDS, STOP, X_OUT, if_, program


def test_render_prints_every_section() -> None:
    p = program(
        [
            (
                "MAIN",
                [
                    if_("F", "'A'", []),
                    if_("F", "'B'", []),
                    if_("G", "'C'", []),
                    if_("G", "'D'", []),
                    if_("G", "'E'", []),
                    X_OUT,
                    STOP,
                ],
            )
        ]
    )
    a, b, c, d, e = sorted(n.id for n in p.cfg.nodes if n.kind is NodeKind.TEST)
    node = next(n.id for n in p.cfg.nodes if "X-OUT" in n.writes)
    report = Report(
        "PROGA",
        node,
        (
            CheckedWay(
                Way((Decision(a, Outcome.TRUE), Decision(b, Outcome.FALSE)), ()),
                Answer.SAT,
                (
                    RouteTest(c, RouteVerdict.EITHER_WAY, Outcome.UNRUN),
                    RouteTest(d, RouteVerdict.IF_IT_RUNS, Outcome.FALSE),
                    RouteTest(e, RouteVerdict.NEVER_RUNS, Outcome.UNRUN),
                ),
            ),
            CheckedWay(
                Way((), ()),
                Answer.UNKNOWN,
                (RouteTest(c, RouteVerdict.GAVE_UP, Outcome.UNRUN),),
            ),
        ),
        3,
        True,
    )

    assert render(p, report) == (
        f"PROGA {node} (0): 2 ways",
        "  way 0: F == 'A' (0) TRUE, F == 'B' (0) FALSE",
        "    either way: G == 'C' (0)",
        "    if it runs: G == 'D' (0) FALSE",
        "    never runs on this way: G == 'E' (0)",
        "  way 1: no deciding tests (solver gave up)",
        "    solver gave up: G == 'C' (0)",
        "  dropped: 3 ways Z3 proved impossible",
        "  (cut at 64 ways: this list is incomplete)",
    )


def test_an_unknown_node_exits_1_naming_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "PROGA.json"
    unit = {
        "programs": [
            {
                "program_id": "PROGA",
                "data_fields": list(FIELDS),
                "paragraphs": [{"name": "MAIN", "statements": [X_OUT, STOP]}],
            }
        ]
    }
    path.write_text(json.dumps(unit), encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        code = main(["--asg", str(path), "--node", "NOPE"])

    assert (code, [r.getMessage() for r in caplog.records]) == (
        1,
        ["NOPE is not a node of PROGA"],
    )
