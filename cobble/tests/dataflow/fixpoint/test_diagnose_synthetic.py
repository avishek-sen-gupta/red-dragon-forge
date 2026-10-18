"""The step-by-step diagnostic, on a small looping program compiled by the real bridge."""

from collections.abc import Callable
from pathlib import Path

import pytest

from cobble.dataflow.fixpoint.diagnose import cli, report
from cobble.dataflow.fixpoint.fixpoint import stepwise
from cobble.dataflow.fixpoint.options import AnalysisOptions
from cobble.parsing.asg_cache import cached_first_program
from cobble.dataflow.fixpoint.scope import Scope

LOOPING = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I                 PIC 9(2).
       01  WS-PGM               PIC X(8).
       01  WS-NEXT              PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-PGM.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               MOVE WS-PGM TO WS-NEXT
               MOVE WS-NEXT TO WS-PGM
           END-PERFORM.
           CALL WS-PGM.
           GOBACK.
"""


def test_the_report_names_where_the_steps_went(
    fixpoint_out: Callable[[str, str], Path], capsys: pytest.CaptureFixture[str]
) -> None:
    out = fixpoint_out("PROGD", LOOPING)
    parsed = out.parent / "parsed"

    lines = report(
        parsed / "PROGD.json", AnalysisOptions(scope=Scope.WHOLE), 50000, 5, True
    ).splitlines()

    assert lines[:2] == [
        "nodes 10, reached 9, steps 15, queue left 0 (settled)",
        "steps that grew a successor: 12 (80%)",
    ]
    assert lines[4] == "        2       2  cycle     4  PARA-001 line 11 (TEST)"
    assert "writer-set sizes over all entries (size: entries):" in lines
    assert lines[
        lines.index("writer-set sizes over all entries (size: entries):") + 1
    ] == ("  1: 8, 2: 11")
    assert lines[-3:] == [
        "         5      7      2          9      2",
        "        10      9      2         18      3",
        "        15      9      0         19      3",
    ]
    assert [line for line in lines if "WS-" in line or "MAIN-PARA" in line] == []
    assert cli(["--asg-dir", str(parsed), "--member", "PROGX"]) == 2
    assert capsys.readouterr().err == (
        f"fields: !! no cached ASG at {parsed / 'PROGX.json'}\n"
    )


def test_every_step_names_the_node_whose_successors_it_changed(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    source = (Path(__file__).parent / "data" / "perf" / "SYNPERFA.cbl").read_text(
        encoding="utf-8"
    )
    out = fixpoint_out("SYNPERFA", source)
    parsed = out.parent / "parsed"
    cfg, walk = stepwise(
        cached_first_program(parsed, parsed / "SYNPERFA.json"), AnalysisOptions(), 50000
    )

    strays = [
        (step.node, changed)
        for step in walk
        for changed in (
            {
                node
                for node, state in step.after.items()
                if step.before.get(node) is not state
            },
        )
        if not changed <= {edge.target for edge in cfg.successors(step.node)}
    ]

    assert strays == []


FILLING_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-NEXT          PIC X(8).
           05  WS-PAD           PIC X(12).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'FILLER' TO WS-PAD.
           EXEC CICS LINK PROGRAM('PROGW') COMMAREA(WS-AREA) END-EXEC.
           CALL WS-NEXT.
           GOBACK.
"""

CALLEE_NEEDS_NOTHING = (
    '{"member":"PROGQ","receives":[],"entry":[],"back":[],"sites":[]}\n'
    '{"member":"PROGW","receives":[["commarea",0]],"entry":[],'
    '"back":[[["commarea",0],[0,8]]],"sites":[]}\n'
)


def test_a_narrowed_diagnosis_walks_as_the_narrowed_fixpoint_does(
    fixpoint_out: Callable[[str, str], Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parsed = fixpoint_out("PROGQ", FILLING_CALLER).parent / "parsed"
    need = tmp_path / "need.jsonl"
    need.write_text(CALLEE_NEEDS_NOTHING, encoding="utf-8")
    common = ["--asg-dir", str(parsed), "--member", "PROGQ", "--every", "100"]
    capsys.readouterr()

    runs = [
        (cli([*common, *flags]), capsys.readouterr())
        for flags in (
            ["--call-targets-only"],
            ["--call-targets-only", "--narrow-areas", str(need)],
            ["--narrow-areas", str(need)],
        )
    ]

    assert [
        (code, out.out.splitlines()[:1], out.out.splitlines()[-1:], out.err)
        for code, out in runs
    ] == [
        (
            0,
            ["nodes 8, reached 7, steps 7, queue left 0 (settled)"],
            ["         7      7      0          3      1"],
            "",
        ),
        (
            0,
            ["nodes 8, reached 7, steps 7, queue left 0 (settled)"],
            ["         7      7      0          2      1"],
            "",
        ),
        (2, [], [], "fields: !! --narrow-areas needs --call-targets-only\n"),
    ]
