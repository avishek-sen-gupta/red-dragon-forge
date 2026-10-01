"""cobble-extents says which member it is on, and what each one yielded."""

import json
import logging
import re
from collections import Counter
from pathlib import Path

import pytest
from cobble.dataflow.fields.emit_extents import emit
from tests.dataflow.fields.test_fields_build_corpus import _program


def _untimed(message: str) -> str:
    return re.sub(r"\d+\.\d+s$", "<t>s", message)


def test_each_member_is_announced_before_it_starts_and_counted_after(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A member can take seconds to lay out, and a run of a few dozen used to say
    nothing between its first line and its last."""
    asg = tmp_path / "asg"
    asg.mkdir()
    (asg / "MEMBERA.json").write_text(json.dumps(_program("PROGA")))
    (asg / "MEMBERB.json").write_text(json.dumps(_program("PROGB")))
    (asg / "MEMBERC.json").write_text("{not json")
    out = tmp_path / "extents.jsonl"
    caplog.set_level(logging.INFO)

    assert emit(asg, out, ()) == 3

    rows = Counter(json.loads(line)["program"] for line in out.read_text().splitlines())
    messages = [_untimed(message) for message in caplog.messages]
    assert messages[:6] == [
        f"extents: 3 members from {asg}",
        "extents: [1/3] MEMBERA",
        f"extents:   MEMBERA {rows['MEMBERA']} rows, <t>s",
        "extents: [2/3] MEMBERB",
        f"extents:   MEMBERB {rows['MEMBERB']} rows, <t>s",
        "extents: [3/3] MEMBERC",
    ]
    assert messages[6].startswith("extents: skipping MEMBERC: unreadable: ")
    assert messages[7:] == [f"extents: wrote {out} (1 skipped)"]
    assert rows == Counter({"MEMBERA": 3, "MEMBERB": 3})
