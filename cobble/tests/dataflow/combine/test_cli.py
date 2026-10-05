import json
from pathlib import Path

import pytest
from cobble.dataflow.combine.cli import cli
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_row
from tests.dataflow.combine.corpus_toml import CONFIG


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


def test_a_member_with_no_results_is_refused_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _member(tmp_path / "fx", "B")

    assert cli(_arguments(tmp_path, "--member", "B", "MISSING")) == 1

    assert "MISSING" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_a_member_named_twice_is_linked_once(tmp_path: Path) -> None:
    _member(tmp_path / "fx", "B")

    assert cli(_arguments(tmp_path, "--member", "B", "B")) == 0

    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "targets.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [(r["caller"], r["candidates"], r["outside"]) for r in rows] == [
        ("B", ["M"], [])
    ]
