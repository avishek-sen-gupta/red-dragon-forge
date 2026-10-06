"""cobble-srccfg-dfs-walk: a CFG file in, an execution-order trace out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.reach.dfs_cli import main
from cobol_asg.asg_types import CobolASG


def _cfg_file(tmp_path: Path, program: str = "PROGA") -> Path:
    """MAIN performs A, which GOBACKs."""
    body = {
        "program_id": program,
        "paragraphs": [
            {"name": "MAIN", "statements": [{"type": "PERFORM", "operands": ["A"]}]},
            {"name": "A", "statements": [{"type": "GOBACK"}]},
        ],
    }
    with cached_asg_dialect_parsers_registered():
        cfg = program_cfg(CobolASG.from_dict(json.loads(json.dumps(body))))
    path = tmp_path / "cfg.jsonl"
    path.write_text(bundle_jsonl(Bundle(seed=program, cfgs=(cfg,))), encoding="utf-8")
    return path


def test_default_mode_is_primary_and_prints_the_trace_and_the_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--cfg", str(_cfg_file(tmp_path)), "--from", "MAIN/0"]) == 0

    out = capsys.readouterr().out
    assert "MAIN/0" in out
    assert "outcome: goback" in out
    assert "=== distinct paragraphs, primary order ===" in out
    assert "1 MAIN" in out
    assert "2 A" in out


def test_mode_tree_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(["--cfg", str(_cfg_file(tmp_path)), "--from", "MAIN/0", "--mode", "tree"])
        == 0
    )

    assert "=== distinct paragraphs, tree order ===" in capsys.readouterr().out


def test_an_unknown_mode_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--cfg", str(_cfg_file(tmp_path)), "--from", "MAIN/0", "--mode", "bogus"])

    assert exit_info.value.code == 2


def test_an_empty_cfg_file_is_an_error_not_an_empty_walk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert main(["--cfg", str(path), "--from", "MAIN/0"]) == 1
    assert "holds no program" in caplog.text
    assert capsys.readouterr().out == ""


def test_a_seed_the_program_does_not_hold_is_an_error_naming_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert main(["--cfg", str(_cfg_file(tmp_path)), "--from", "NOWHERE/0"]) == 1
    assert "has no node NOWHERE/0" in caplog.text


def test_a_missing_cfg_file_is_an_error_not_a_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert main(["--cfg", str(tmp_path / "absent.jsonl"), "--from", "MAIN/0"]) == 1
    assert "absent.jsonl" in caplog.text
