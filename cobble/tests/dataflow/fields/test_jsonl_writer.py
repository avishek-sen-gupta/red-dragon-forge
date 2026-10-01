from pathlib import Path

import pytest
from cobble.dataflow.fields.side_tables import jsonl_writer


def test_a_block_that_raises_publishes_nothing(tmp_path: Path) -> None:
    """An interrupted table stays a .tmp: renamed into place, it would read as
    complete to every consumer."""
    out = tmp_path / "table.jsonl"

    with pytest.raises(RuntimeError, match="interrupted"):
        with jsonl_writer(out) as writer:
            writer.add_row("a", '{"a": 1}')
            raise RuntimeError("interrupted")

    assert not out.exists()
    assert out.with_suffix(".jsonl.tmp").read_text() == '{"a": 1}\n'
