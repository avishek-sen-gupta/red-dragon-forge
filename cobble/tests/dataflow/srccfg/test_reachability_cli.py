"""cobble-srccfg-reachability-walk: a CFG file in, the reached subgraph and its outcomes out."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl, load_bundle
from cobble.dataflow.srccfg.closure import main as build_main
from cobble.dataflow.srccfg.dot import dot_of
from cobble.dataflow.srccfg.dot import main as dot_main
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.reach.reachability_cli import main
from cobble.dataflow.srccfg.rows.cfg_row import CFG_ROWS
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow
from cobble.dataflow.srccfg.rows.summary_row import CfgSummaryRow
from cobol_asg.asg_types import CobolASG

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REACHP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG              PIC X.
       01  WS-A                 PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA THRU WORK-EXIT.
           MOVE 'DONE' TO WS-A.
           STOP RUN.
       WORK-PARA.
           IF WS-FLAG = 'Y'
               GO TO FAIL-PARA
           END-IF.
           MOVE 'WORK' TO WS-A.
       WORK-EXIT.
           EXIT.
       FAIL-PARA.
           MOVE 'FAIL' TO WS-A.
           GOBACK.
"""


def _cfg_file(tmp_path: Path, *programs: str) -> Path:
    """A closure-shaped file of one-paragraph programs, each MAIN performing A."""

    def asg(program: str) -> CobolASG:
        body = {
            "program_id": program,
            "paragraphs": [
                {
                    "name": "MAIN",
                    "statements": [{"type": "PERFORM", "operands": ["A"]}],
                },
                {"name": "A", "statements": [{"type": "GOBACK"}]},
            ],
        }
        with cached_asg_dialect_parsers_registered():
            return CobolASG.from_dict(json.loads(json.dumps(body)))

    cfgs = tuple(program_cfg(asg(program)) for program in programs)
    path = tmp_path / "cfg.jsonl"
    path.write_text(bundle_jsonl(Bundle(seed=programs[0], cfgs=cfgs)), encoding="utf-8")
    return path


def test_the_command_streams_the_rows_and_says_nothing_else_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--cfg", str(_cfg_file(tmp_path, "PROGA")), "--from", "MAIN/0"]) == 0

    rows = [
        CFG_ROWS.validate_json(line) for line in capsys.readouterr().out.splitlines()
    ]

    assert [row.type for row in rows][:2] == ["program", "node"]
    assert {
        (row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)
    } == {("goback", "A/0")}
    assert rows[-1] == CfgSummaryRow(type=CfgRowType.SUMMARY, seed="MAIN/0", states=2)


@pytest.mark.parametrize(
    ("argv_tail", "message"),
    (
        (["--from", "MAIN/0"], ""),
        (["--from", "MAIN/7"], "PROGA has no node MAIN/7"),
    ),
    ids=("missing-file", "absent-seed"),
)
def test_a_seed_the_file_does_not_hold_is_an_error_naming_the_program(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    argv_tail: list[str],
    message: str,
) -> None:
    """The walk runs in the file's first program; a seed elsewhere -- in a callee of a
    closure, say -- is reported against the program searched, and nothing reaches
    stdout. A file that is not there is the same: an error, an exit code, no rows."""
    cfg = (
        _cfg_file(tmp_path, "PROGA", "PROGB") if message else tmp_path / "absent.jsonl"
    )

    assert main(["--cfg", str(cfg), *argv_tail]) == 1
    assert capsys.readouterr().out == ""
    assert (message or "absent.jsonl") in caplog.text


def test_an_empty_cfg_file_is_an_error_not_an_empty_walk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert main(["--cfg", str(path), "--from", "MAIN/0"]) == 1
    assert capsys.readouterr().out == ""
    assert "holds no program" in caplog.text


def test_a_reader_that_stops_early_ends_the_command_quietly(tmp_path: Path) -> None:
    """Stopping early is a use, not a failure: `| head` closes the pipe while rows
    are still coming, and the command exits 0 with no traceback."""
    chain = [
        {
            "name": f"P{at}",
            "statements": [
                {"type": "MOVE", "operands": [{"name": "'A'"}, {"name": "WS-A"}]}
            ],
        }
        for at in range(600)
    ]
    body = {
        "program_id": "PROGA",
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    {"type": "PERFORM", "operands": ["P0"], "thru": "P599"},
                    {"type": "GOBACK"},
                ],
            },
            *chain,
        ],
    }
    with cached_asg_dialect_parsers_registered():
        cfg = program_cfg(CobolASG.from_dict(json.loads(json.dumps(body))))
    path = tmp_path / "long.jsonl"
    path.write_text(bundle_jsonl(Bundle(seed="PROGA", cfgs=(cfg,))), encoding="utf-8")
    command = (
        "import sys; from cobble.dataflow.srccfg.reach.reachability_cli import main; "
        f"sys.exit(main(['--cfg', {str(path)!r}, '--from', 'MAIN/0']))"
    )
    reading, writing = os.pipe()
    errors = tmp_path / "stderr.txt"
    with errors.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-c", command], stdout=writing, stderr=stderr
        )
    os.close(writing)
    with os.fdopen(reading, "rb") as stdout:
        first = stdout.readline()

    assert (process.wait(), json.loads(first)["type"]) == (0, "program")
    assert errors.read_text(encoding="utf-8") == ""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def test_a_compiled_program_reaches_its_range_and_renders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: the bridge's ASG, cobble-srccfg-build's file, this command's rows,
    and cobble-srccfg-dot drawing them. The range is WORK-PARA THRU WORK-EXIT; a
    GO TO out of it ends in GOBACK, the other branch returns."""
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path / "parsed"
    cache.mkdir()
    source = tmp_path / "REACHP.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_one(
        Job(source, cache / "REACHP.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{cache}"\n', encoding="utf-8")
    built = tmp_path / "REACHP.jsonl"
    assert build_main(["--config", str(config), "REACHP", "--output", str(built)]) == 0

    assert main(["--cfg", str(built), "--from", "MAIN-PARA/0"]) == 0
    out = tmp_path / "reach.jsonl"
    out.write_text(capsys.readouterr().out, encoding="utf-8")
    rows = [CFG_ROWS.validate_json(line) for line in out.read_text().splitlines()]

    assert list(
        dict.fromkeys(row.paragraph for row in rows if isinstance(row, CfgNodeRow))
    ) == ["MAIN-PARA", "WORK-PARA", "FAIL-PARA", "WORK-EXIT"]
    assert {
        (row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)
    } == {
        ("goback", "FAIL-PARA/1"),
        ("returns", "MAIN-PARA/1"),
    }
    assert [row.type for row in rows if row.type in ("unresolved", "refused")] == []
    assert isinstance(rows[-1], CfgSummaryRow)
    assert dot_main(["--cfg", str(out), "--output", str(tmp_path / "reach.dot")]) == 0
    assert (tmp_path / "reach.dot").read_text(encoding="utf-8") == (
        f"{dot_of(load_bundle(out).cfgs, ())}\n"
    )
