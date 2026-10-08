"""Every combine heartbeat says how far through the round it is."""

import logging

import pytest

from cobble.dataflow.combine.link import position
from cobble.dataflow.combine.walk import walked


def test_a_walk_heartbeat_says_where_in_the_round_it_is(
    caplog: pytest.LogCaptureFixture,
) -> None:
    label = position(1, 4210, 18952, 812, 3779, "PROGA")

    with caplog.at_level(logging.INFO):
        state = walked(
            0,
            lambda vertex: (frozenset({vertex}), (vertex + 1,) if vertex < 2 else ()),
            lambda left, right: left | right,
            frozenset[int](),
            label=label,
            heartbeat=0.0,
            spread=lambda seen: f" across {len(seen)}/9 programs",
        )

    assert state.found == frozenset({0, 1, 2})
    assert label == "round 1: jump 4210/18952 (22%), program 812/3779 PROGA"
    assert [record.getMessage() for record in caplog.records] == [
        f"combine:     {label}: walk step 1, 2 seen across 2/9 programs, 1 frontier",
        f"combine:     {label}: walk step 2, 3 seen across 3/9 programs, 1 frontier",
        f"combine:     {label}: walk step 3, 3 seen across 3/9 programs, 0 frontier",
    ]
