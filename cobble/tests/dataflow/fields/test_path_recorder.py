from __future__ import annotations

import io
import json

from cobble.dataflow.fields.trace import Dep
from cobble.dataflow.fields.trace_report import (
    _path_record_row,
    _PathRecord,
    _PathRecorder,
)
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

_RECORD = _PathRecord(
    path_index=0,
    nodes=("PROG/PARA-A/label", "PROG/PARA-A/0", "PROG/PARA-B/label"),
    deps=({"kind": "dep", "program": "PROG", "node": "PROG/PARA-A/0"},),
)


def test_path_record_row_kind():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["kind"] == "path"


def test_path_record_row_path_index():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["path_index"] == 0


def test_path_record_row_nodes():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["nodes"] == list(_RECORD.nodes)


def test_path_record_row_no_branch_edges_new():
    parsed = json.loads(_path_record_row(_RECORD))
    assert "branch_edges_new" not in parsed


def test_path_record_row_deps():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["deps"] == list(_RECORD.deps)


def test_path_record_is_frozen() -> None:
    import dataclasses

    assert dataclasses.fields(_RECORD)  # confirms it is a dataclass
    try:
        _RECORD.path_index = 1  # type: ignore
        raise AssertionError("should be frozen")
    except (dataclasses.FrozenInstanceError, AttributeError):
        pass


# --- _PathRecorder tests ---

_WS = RegionId.WORKING_STORAGE
_EXT = FieldExtent(
    field_name="F", region=_WS, start=0, length=4, precision=Precision.EXACT
)
_DEP = Dep(
    program="P",
    node="P/A/0",
    target=_EXT,
    origin="LITERAL",
    source=_EXT,
    definers=(),
    via="",
    source_program="P",
)


def test_path_recorder_writes_path_record_kind_and_index() -> None:
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    recorder.record_dep(_DEP)
    recorder.flush(("P/A/label", "P/A/0"))
    buf.seek(0)
    lines = [line for line in buf.read().splitlines() if line.strip()]
    row = json.loads(lines[0])
    assert row["kind"] == "path"
    assert row["path_index"] == 0


def test_path_recorder_writes_path_record_nodes() -> None:
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    recorder.record_dep(_DEP)
    recorder.flush(("P/A/label", "P/A/0"))
    buf.seek(0)
    lines = [line for line in buf.read().splitlines() if line.strip()]
    row = json.loads(lines[0])
    assert "P/A/label" in row["nodes"]


def test_path_recorder_increments_index() -> None:
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    recorder.flush(("P/A/label",))
    recorder.flush(("P/B/label",))
    buf.seek(0)
    rows = [json.loads(line) for line in buf.read().splitlines() if line.strip()]
    assert rows[0]["path_index"] == 0
    assert rows[1]["path_index"] == 1


def test_path_recorder_clears_deps_between_paths() -> None:
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    recorder.record_dep(_DEP)
    recorder.flush(("P/A/0",))
    recorder.flush(("P/B/0",))  # no record_dep before this
    buf.seek(0)
    rows = [json.loads(line) for line in buf.read().splitlines() if line.strip()]
    assert len(rows[1]["deps"]) == 0


def test_path_recorder_flush_returns_self() -> None:
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    result = recorder.flush(("P/A/0",))
    assert result is recorder


def test_path_recorder_record_dep_returns_self() -> None:
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    result = recorder.record_dep(_DEP)
    assert result is recorder


# --- CLI flag integration tests ---


def test_record_paths_flag_accepted_without_error(tmp_path):
    """CLI accepts --record-paths; argparser does not raise."""
    from cobble.dataflow.fields.trace_report import _parser

    args = _parser().parse_args(
        [
            "MYPROG",
            "--asg-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "deps.jsonl"),
            "--record-paths",
            str(tmp_path / "paths.jsonl"),
        ]
    )
    assert str(args.record_paths) == str(tmp_path / "paths.jsonl")


def test_record_paths_flag_absent_gives_none(tmp_path):
    """Omitting --record-paths leaves the attribute as None."""
    from cobble.dataflow.fields.trace_report import _parser

    args = _parser().parse_args(
        [
            "MYPROG",
            "--asg-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "deps.jsonl"),
        ]
    )
    assert args.record_paths is None


def test_record_paths_flag_nested_path_accepted(tmp_path):
    """--record-paths accepts a path whose parent directory does not exist yet."""
    from cobble.dataflow.fields.trace_report import _parser

    args = _parser().parse_args(
        [
            "MYPROG",
            "--asg-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "deps.jsonl"),
            "--record-paths",
            str(tmp_path / "subdir" / "paths.jsonl"),
        ]
    )
    assert str(args.record_paths) == str(tmp_path / "subdir" / "paths.jsonl")
