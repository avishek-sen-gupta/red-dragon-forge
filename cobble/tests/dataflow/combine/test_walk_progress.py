"""Every combine heartbeat says how far through the round it is, and how far its memo has got."""

import logging

import pytest

from cobble.dataflow.combine.closures import Closures
from cobble.dataflow.combine.link import position


def test_a_heartbeat_says_where_in_the_round_it_is_and_how_many_places_are_answered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    label = position(1, 4210, 18952, 812, 3779, "PROGA")
    closures = Closures(
        lambda vertex: (frozenset({vertex}), (vertex + 1,) if vertex < 2 else ()),
        lambda left, right: left | right,
        frozenset[int](),
        heartbeat=0.0,
    )

    with caplog.at_level(logging.INFO):
        found = closures.of(0, label)

    assert found == frozenset({0, 1, 2})
    assert label == "round 1: jump 4210/18952 (22%), program 812/3779 PROGA"
    assert [record.getMessage() for record in caplog.records] == [
        f"combine:     {label}: 1 vertices answered, 2 on the stack",
        f"combine:     {label}: 2 vertices answered, 1 on the stack",
        f"combine:     {label}: 3 vertices answered, 0 on the stack",
    ]
