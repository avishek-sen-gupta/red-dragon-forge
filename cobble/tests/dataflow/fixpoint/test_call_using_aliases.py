"""CALL USING, compiled by the real bridge: each argument shares bytes with the
callee parameter at its position in the callee's PROCEDURE DIVISION USING.

SUBP declares LK-B before LK-A but lists LK-A first, so binding by declaration
order would pair WS-ONE with LK-B. BY REFERENCE storage is shared both ways, so
its alias returns; BY CONTENT is a copy the callee cannot write back through.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HEAD              PIC X(4).
       01  WS-ONE               PIC X(6).
       01  WS-TWO               PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUBP' USING WS-ONE BY CONTENT WS-TWO.
           CALL 'SUBP' USING BY CONTENT 'LIT'.
           GOBACK.
"""

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-B                 PIC X(8).
       01  LK-A                 PIC X(6).
       PROCEDURE DIVISION USING LK-A LK-B.
       MAIN-PARA.
           MOVE LK-B TO LK-A.
           GOBACK.
"""


@pytest.fixture(scope="module")
def aliases(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
) -> list[tuple[str, str, str, bool, str]]:
    out = fixpoint_corpus({"CALLR": CALLER, "SUBP": CALLEE})
    return sorted(
        (
            row["node"],
            row["caller_extent"],
            row["callee_extent"],
            row["returns"],
            row["reason"],
        )
        for row in map(json.loads, (out / "aliases.jsonl").read_text().splitlines())
    )


def test_each_argument_shares_bytes_with_the_parameter_at_its_position(
    aliases: list[tuple[str, str, str, bool, str]],
) -> None:
    assert aliases == [
        ("MAIN-PARA/0", "WS-ONE@working_storage[4:10]", "LK-A@linkage[8:14]", True, ""),
        (
            "MAIN-PARA/0",
            "WS-TWO@working_storage[10:18]",
            "LK-B@linkage[0:8]",
            False,
            "",
        ),
        ("MAIN-PARA/1", "", "", False, "argument-is-not-a-field"),
    ]


def test_the_query_follows_an_argument_in_and_only_a_reference_back_out(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = fixpoint_corpus({"CALLR": CALLER, "SUBP": CALLEE})
    capsys.readouterr()

    assert {
        subject: _landings(out, subject, capsys)
        for subject in ("CALLR.WS-TWO", "SUBP.LK-A", "SUBP.LK-B")
    } == {
        "CALLR.WS-TWO": [
            "hop 1  depth 1  SUBP.LK-B  LK-B@linkage[0:8]  via CALLR:MAIN-PARA/0",
            "hop 1  depth 2  SUBP.LK-A  LK-A@linkage[8:14]  via CALLR:MAIN-PARA/0",
            "hop 2  depth 3  CALLR.WS-ONE  WS-ONE@working_storage[4:10]"
            "  via CALLR:MAIN-PARA/0",
        ],
        "SUBP.LK-A": [
            "hop 1  depth 1  CALLR.WS-ONE  WS-ONE@working_storage[4:10]"
            "  via CALLR:MAIN-PARA/0",
        ],
        "SUBP.LK-B": [
            "hop 0  depth 1  SUBP.LK-A  LK-A@linkage[8:14]",
            "hop 1  depth 2  CALLR.WS-ONE  WS-ONE@working_storage[4:10]"
            "  via CALLR:MAIN-PARA/0",
        ],
    }


def _landings(out: Path, subject: str, capsys: pytest.CaptureFixture[str]) -> list[str]:
    from cobble.dataflow.fixpoint.query import cli

    assert (
        cli(
            [
                "reaches",
                subject,
                "--fixpoint-dir",
                str(out),
                "--extents",
                str(out.parent / "extents.jsonl"),
                "--across-calls",
            ]
        )
        == 0
    )
    return [
        line.strip()
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("  hop ")
    ]
