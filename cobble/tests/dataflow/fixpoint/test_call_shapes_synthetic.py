"""Every shape of a CALL through a data item, compiled by the real bridge, resolves."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.fields.emit_extents import emit
from cobble.dataflow.fixpoint.build_corpus import cli

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

PROGRAM = "CALLSHP"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLSHP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG              PIC X.
       01  WS-FIXED             PIC X(8) VALUE 'PROGA'.
       01  WS-SOMETIMES         PIC X(8) VALUE 'PROGB'.
       01  WS-NOVALUE           PIC X(8).
       01  WS-PGM               PIC X(8).
       01  WS-REC.
           05  WS-PGM           PIC X(8).
       01  WS-LONG              PIC X(16).
       01  WS-ARG1              PIC X(4).
       01  WS-ARG2              PIC X(4).
       01  WS-RET               PIC S9(4) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGC' TO WS-PGM OF WS-REC.
           MOVE 'PROGD   PROGE   ' TO WS-LONG.
           IF WS-FLAG = 'Y'
               MOVE 'PROGF' TO WS-SOMETIMES
           END-IF.
           CALL WS-FIXED.
           CALL WS-PGM OF WS-REC USING WS-ARG1 WS-ARG2.
           CALL WS-PGM OF WS-REC USING BY REFERENCE WS-ARG1
               BY CONTENT WS-ARG2.
           CALL WS-PGM OF WS-REC USING WS-ARG1 RETURNING WS-RET.
           CALL WS-PGM OF WS-REC USING WS-ARG1
               ON EXCEPTION DISPLAY 'NONE'
           END-CALL.
           CALL WS-LONG(1:8).
           CALL WS-LONG(9:8) USING WS-ARG1.
           CALL WS-SOMETIMES USING WS-ARG1.
           CALL WS-NOVALUE.
           CALL 'PROGG' USING WS-ARG1.
           STOP RUN.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


@pytest.fixture(scope="module")
def targets(
    tmp_path_factory: pytest.TempPathFactory,
) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    from cobble.parsing.parse_corpus import Job, parse_one

    workspace = tmp_path_factory.mktemp("call-shapes")
    source = workspace / f"{PROGRAM}.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    cache = workspace / "parsed"
    cache.mkdir()
    parsed = parse_one(
        Job(source, cache / f"{PROGRAM}.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    extents = workspace / "extents.jsonl"
    assert emit(cache, extents, (), max_workers=1) == 0
    out = workspace / "out"
    cli(
        [
            "--asg-dir",
            str(cache),
            "--out-dir",
            str(out),
            "--extents",
            str(extents),
            "--member",
            PROGRAM,
            "--max-workers",
            "1",
        ]
    )
    return [
        (
            row["node"],
            row["expression"],
            tuple(row["candidates"]),
            tuple(row["reasons"]),
        )
        for row in map(json.loads, (out / "targets.jsonl").read_text().splitlines())
    ]


def test_every_call_through_a_data_item_gets_a_row_and_a_literal_call_does_not(
    targets: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]],
) -> None:
    assert targets == [
        ("MAIN-PARA/3", "WS-FIXED", ("PROGA",), ()),
        ("MAIN-PARA/4", "WS-PGM", ("PROGC",), ()),
        ("MAIN-PARA/5", "WS-PGM", ("PROGC",), ()),
        ("MAIN-PARA/6", "WS-PGM", ("PROGC",), ()),
        ("MAIN-PARA/7", "WS-PGM", ("PROGC",), ()),
        ("MAIN-PARA/8", "WS-LONG", ("PROGD",), ()),
        ("MAIN-PARA/9", "WS-LONG", ("PROGE",), ()),
        ("MAIN-PARA/10", "WS-SOMETIMES", ("PROGB", "PROGF"), ()),
        ("MAIN-PARA/11", "WS-NOVALUE", (), ("uninitialised",)),
    ]
