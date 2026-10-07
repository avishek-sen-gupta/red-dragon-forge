import json
import logging
from pathlib import Path

import pytest
from cobble.dataflow.combine.cli import cli
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_row
from tests.dataflow.combine.corpus_toml import CONFIG
from tests.dataflow.combine.linked_rows import TargetRow, target_rows


def _member(fixpoint: Path, name: str) -> None:
    member = fixpoint / "members" / name
    member.mkdir(parents=True)
    jump = Jump(name, "X", 3, JumpKind.XCTL, False, target=Fact(values=("M",)))
    (member / "jumps.jsonl").write_text(jump_row(jump) + "\n", encoding="utf-8")
    site = {
        "caller": name,
        "node": "X",
        "transfer": "CICS_XCTL",
        "expression": "WS-NEXT",
    }
    (member / "targets.jsonl").write_text(json.dumps(site) + "\n", encoding="utf-8")


def _arguments(tmp_path: Path, *selection: str) -> list[str]:
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=tmp_path / "asg"), encoding="utf-8")
    (tmp_path / "asg").mkdir(exist_ok=True)
    return [
        "--config",
        str(config),
        "--fixpoint-dir",
        str(tmp_path / "fx"),
        "--out-dir",
        str(tmp_path / "out"),
        *selection,
    ]


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "cobble.dataflow.combine.cli"
    ]


def test_a_member_with_no_results_is_refused_and_nothing_is_written(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _member(tmp_path / "fx", "B")

    assert cli(_arguments(tmp_path, "--member", "B", "MISSING")) == 1

    assert _messages(caplog) == ["combine: !! no fixpoint results for: MISSING"]
    assert not (tmp_path / "out").exists()


def test_a_missing_fixpoint_directory_is_refused_not_a_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert cli(_arguments(tmp_path, "--all")) == 2

    assert _messages(caplog) == [
        f"combine: !! no fixpoint results at {tmp_path / 'fx' / 'members'}"
    ]
    assert not (tmp_path / "out").exists()


def test_a_member_named_twice_is_linked_once_and_reports_the_outside(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _member(tmp_path / "fx", "B")
    caplog.set_level(logging.INFO)

    assert cli(_arguments(tmp_path, "--member", "B", "B")) == 0

    assert target_rows(tmp_path / "out" / "targets.jsonl") == [
        TargetRow(
            caller="B",
            node="X",
            transfer="CICS_XCTL",
            expression="WS-NEXT",
            candidates=("M",),
            reasons=(),
            dropped=(),
            outside=(),
        )
    ]
    assert _messages(caplog) == [
        "combine: 1 rounds, 0 discovered edges",
        "combine: 0 outside jumps with unresolved targets, "
        "0 outside programs without results",
    ]


def test_all_reports_no_outside(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _member(tmp_path / "fx", "B")
    caplog.set_level(logging.INFO)

    assert cli(_arguments(tmp_path, "--all")) == 0

    assert _messages(caplog) == ["combine: 1 rounds, 0 discovered edges"]


def test_a_config_whose_parse_cache_is_missing_is_refused_not_an_empty_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _member(tmp_path / "fx", "B")
    arguments = _arguments(tmp_path, "--all")
    (tmp_path / "asg").rmdir()

    assert cli(arguments) == 2

    assert _messages(caplog) == [f"combine: !! no parse cache at {tmp_path / 'asg'}"]
    assert not (tmp_path / "out").exists()


def test_a_missing_config_is_refused_not_a_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _member(tmp_path / "fx", "B")
    arguments = _arguments(tmp_path, "--all")
    (tmp_path / "corpus.toml").unlink()

    assert cli(arguments) == 2

    assert _messages(caplog) == [
        f"combine: !! no corpus config at {tmp_path / 'corpus.toml'}"
    ]
    assert not (tmp_path / "out").exists()
