"""What one fixpoint run over a fixture program cost, at one commit."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixpointCost:
    """The deterministic counts the test compares, and the time and memory it records."""

    commit: str
    nodes: int
    dequeues: int
    settled: bool
    source_extents: int
    largest_state: int
    value_extents: int
    peak_rss_mb: int
    seconds: float
