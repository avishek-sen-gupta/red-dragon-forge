"""A long pass over rows logs how far it has got."""

from __future__ import annotations

import logging

import pytest

from cobble.experimental.partition.progress import counted
from cobble.experimental.partition.tally import PROGRESS_EVERY, Tally


def test_a_counted_pass_yields_every_item_and_logs_each_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    items = tuple(range(2 * PROGRESS_EVERY + 1))
    programs = ("P", "Q", "R")

    with caplog.at_level(logging.INFO):
        assert (
            tuple(counted(items, Tally("partition graph", "dep rows"), len(items)))
            == items
        )
        assert (
            tuple(
                counted(programs, Tally("partition render", "programs laid out", 1), 3)
            )
            == programs
        )

    assert [record.getMessage() for record in caplog.records] == [
        f"partition graph: dep rows {PROGRESS_EVERY}/{len(items)}",
        f"partition graph: dep rows {2 * PROGRESS_EVERY}/{len(items)}",
        f"partition graph: dep rows {len(items)}/{len(items)} done",
        "partition render: programs laid out 1/3",
        "partition render: programs laid out 2/3",
        "partition render: programs laid out 3/3",
        "partition render: programs laid out 3/3 done",
    ]
