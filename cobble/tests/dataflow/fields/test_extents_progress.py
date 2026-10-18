"""cobble-extents lays members out in parallel and says what each one yielded."""

import json
import logging
import re
from collections import Counter
from pathlib import Path

import pytest
from cobble.dataflow.fields.emit_extents import cli, emit
from tests.dataflow.fields.test_fields_build_corpus import _program


def _untimed(message: str) -> str:
    return re.sub(r"\d+\.\d+s$", "<t>s", message)


def _cache(tmp_path: Path) -> Path:
    asg = tmp_path / "asg"
    asg.mkdir()
    for member, program in (
        ("MEMBERA", "PROGA"),
        ("MEMBERB", "PROGB"),
        ("MEMBERD", "PROGD"),
    ):
        (asg / f"{member}.json").write_text(
            json.dumps({"programs": [_program(program)]})
        )
    (asg / "MEMBERC.json").write_text("{not json")
    return asg


def test_each_member_is_reported_in_order_as_its_rows_are_written(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A member can take seconds to lay out, and a run of a few dozen used to say
    nothing between its first line and its last. Workers finish out of order; the
    report and the file follow the member order regardless."""
    asg = _cache(tmp_path)
    out = tmp_path / "extents.jsonl"
    caplog.set_level(logging.INFO)

    assert emit(asg, out, (), max_workers=2) == 3

    rows = Counter(json.loads(line)["program"] for line in out.read_text().splitlines())
    messages = [_untimed(message) for message in caplog.messages]
    assert rows == Counter({"MEMBERA": 3, "MEMBERB": 3, "MEMBERD": 3})
    assert messages[:3] == [
        f"extents: 4 members from {asg}, 2 workers",
        "extents: [1/4] MEMBERA 3 rows, <t>s",
        "extents: [2/4] MEMBERB 3 rows, <t>s",
    ]
    assert messages[3].startswith("extents: [3/4] MEMBERC skipped: unreadable: ")
    assert messages[4:] == [
        "extents: [4/4] MEMBERD 3 rows, <t>s",
        f"extents: wrote {out} (1 skipped)",
    ]


def test_four_workers_write_the_table_one_worker_writes(tmp_path: Path) -> None:
    asg = _cache(tmp_path)
    serial, parallel = tmp_path / "serial.jsonl", tmp_path / "parallel.jsonl"

    assert emit(asg, serial, (), max_workers=1) == 3
    assert emit(asg, parallel, (), max_workers=4) == 3

    assert parallel.read_bytes() == serial.read_bytes()


def test_the_worker_count_is_parsed_and_must_be_positive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asg = _cache(tmp_path)
    out = tmp_path / "extents.jsonl"

    assert cli(["--asg-dir", str(asg), "--out", str(out), "--max-workers", "2"]) == 3
    assert out.read_text().count("\n") == 9

    with pytest.raises(SystemExit) as refused:
        cli(["--asg-dir", str(asg), "--out", str(out), "--max-workers", "0"])
    assert refused.value.code == 2
    assert "needs at least one worker, got 0" in capsys.readouterr().err
