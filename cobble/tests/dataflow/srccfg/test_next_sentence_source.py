"""NEXT SENTENCE, from COBOL source through cobble-srccfg-build and -walk.

The STOP RUN after END-IF is in the same sentence as the IF, so the arm holding
NEXT SENTENCE skips it and the PERFORM returns; the ELSE arm runs into it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.srccfg.closure import main as build_main
from cobble.dataflow.srccfg.reach.cli import main as walk_main
from cobble.dataflow.srccfg.rows.cfg_row import CFG_ROWS
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEXTSP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X.
       01  WS-B                 PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM P1.
           GOBACK.
       P1.
           IF WS-A = 'Y'
               NEXT SENTENCE
           ELSE
               MOVE 'N' TO WS-B
           END-IF
           STOP RUN.
           MOVE 'Z' TO WS-B.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def test_next_sentence_skips_what_follows_end_if_in_its_sentence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path / "parsed"
    cache.mkdir()
    source = tmp_path / "NEXTSP.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_one(
        Job(source, cache / "NEXTSP.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{cache}"\n', encoding="utf-8")
    built = tmp_path / "NEXTSP.jsonl"
    assert build_main(["--config", str(config), "NEXTSP", "--output", str(built)]) == 0

    assert walk_main(["--cfg", str(built), "--from", "MAIN-PARA/0"]) == 0
    rows = [
        CFG_ROWS.validate_json(line) for line in capsys.readouterr().out.splitlines()
    ]

    assert {
        (row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)
    } == {("stop-run", "P1/1"), ("returns", "MAIN-PARA/1")}
    assert {row.id for row in rows if isinstance(row, CfgNodeRow)} == {
        "MAIN-PARA/0",
        "P1#label",
        "P1/0#test",
        "P1/0.then.0",
        "P1#sentence.0",
        "P1/2",
        "P1#end",
        "MAIN-PARA/1",
        "P1/0.else.0",
        "P1/1",
    }
