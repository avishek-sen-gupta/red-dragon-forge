"""EXIT PARAGRAPH and EXIT SECTION, from COBOL source through cobble's targets.

The desugar tests build the ASG by hand; this one compiles real COBOL with the
bridge, so it also pins that the bridge's EXIT kinds are the ones desugar reads.
Each EXIT stands in front of a STOP RUN: when the jump is lowered, the walk returns
past it, and when it is not, the STOP RUN ends the branch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.srccfg.closure import main as build_main
from cobble.dataflow.srccfg.reach.reachability_cli import main as walk_main
from cobble.dataflow.srccfg.rows.cfg_row import CFG_ROWS, CfgRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(4).
       PROCEDURE DIVISION.
       MAIN SECTION.
       MAIN-PARA.
           PERFORM CHECK-PARA.
           PERFORM WORK.
           GOBACK.
       CHECK-PARA.
           EXIT PARAGRAPH.
           STOP RUN.
       WORK SECTION.
       W1.
           EXIT SECTION.
       W2.
           MOVE 'LATE' TO WS-A.
           STOP RUN.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def test_a_walk_returns_past_what_each_exit_leaves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path / "parsed"
    cache.mkdir()
    source = tmp_path / "EXITP.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_one(
        Job(source, cache / "EXITP.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{cache}"\n', encoding="utf-8")
    built = tmp_path / "EXITP.jsonl"
    assert build_main(["--config", str(config), "EXITP", "--output", str(built)]) == 0

    walks = {
        seed: _walk(built, seed, capsys) for seed in ("MAIN-PARA/0", "MAIN-PARA/1")
    }

    assert {seed: _outcomes(rows) for seed, rows in walks.items()} == {
        "MAIN-PARA/0": {("returns", "MAIN-PARA/1")},
        "MAIN-PARA/1": {("returns", "MAIN-PARA/2")},
    }
    assert {seed: _reached(rows) for seed, rows in walks.items()} == {
        "MAIN-PARA/0": {
            "MAIN-PARA/0",
            "CHECK-PARA#label",
            "CHECK-PARA/0",
            "CHECK-PARA#end",
            "MAIN-PARA/1",
        },
        "MAIN-PARA/1": {
            "MAIN-PARA/1",
            "WORK#label",
            "W1#label",
            "W1/0",
            "WORK#end",
            "MAIN-PARA/2",
        },
    }


def _walk(built: Path, seed: str, capsys: pytest.CaptureFixture[str]) -> list[CfgRow]:
    assert walk_main(["--cfg", str(built), "--from", seed]) == 0
    return [
        CFG_ROWS.validate_json(line) for line in capsys.readouterr().out.splitlines()
    ]


def _outcomes(rows: list[CfgRow]) -> set[tuple[str, str]]:
    return {
        (row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)
    }


def _reached(rows: list[CfgRow]) -> set[str]:
    return {row.id for row in rows if isinstance(row, CfgNodeRow)}
