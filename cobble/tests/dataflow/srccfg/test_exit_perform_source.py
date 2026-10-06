"""EXIT PERFORM and EXIT PERFORM CYCLE, from COBOL source through cobble-srccfg-build
and -walk.

Each loop body ends in STOP RUN, so leaving the first loop and reaching the second
loop's VARYING step are both only possible through the EXITs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.srccfg.closure import main as build_main
from cobble.dataflow.srccfg.reach.reachability_cli import main as walk_main
from cobble.dataflow.srccfg.rows.cfg_row import CFG_ROWS
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITPP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X.
       01  WS-B                 PIC X.
       01  WS-K                 PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM P1.
           GOBACK.
       P1.
           PERFORM UNTIL WS-A = 'Y'
               IF WS-B = 'X'
                   EXIT PERFORM
               END-IF
               STOP RUN
           END-PERFORM.
           PERFORM VARYING WS-K FROM 1 BY 1 UNTIL WS-K > 3
               IF WS-B = 'Z'
                   EXIT PERFORM CYCLE
               END-IF
               STOP RUN
           END-PERFORM.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def test_exit_perform_leaves_the_loop_and_cycle_reaches_its_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path / "parsed"
    cache.mkdir()
    source = tmp_path / "EXITPP.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_one(
        Job(source, cache / "EXITPP.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{cache}"\n', encoding="utf-8")
    built = tmp_path / "EXITPP.jsonl"
    assert build_main(["--config", str(config), "EXITPP", "--output", str(built)]) == 0

    assert walk_main(["--cfg", str(built), "--from", "MAIN-PARA/0"]) == 0
    rows = [
        CFG_ROWS.validate_json(line) for line in capsys.readouterr().out.splitlines()
    ]

    assert {
        (row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)
    } == {
        ("returns", "MAIN-PARA/1"),
        ("stop-run", "P1/0.body.1"),
        ("stop-run", "P1/1.body.1"),
    }
    assert {row.id for row in rows if isinstance(row, CfgNodeRow)} == {
        "MAIN-PARA/0",
        "MAIN-PARA/1",
        "P1#label",
        "P1/0#loop#test",
        "P1/0.body.0#test",
        "P1/0.body.0.then.0",
        "P1/0.body.1",
        "P1/0#leave",
        "P1/1#init",
        "P1/1#loop#test",
        "P1/1.body.0#test",
        "P1/1.body.0.then.0",
        "P1/1.body.1",
        "P1/1#cycle",
        "P1/1#step",
        "P1#end",
    }
