"""What a counted run over rows reports: the stage, what it counts, and how often."""

from __future__ import annotations

from dataclasses import dataclass

PROGRESS_EVERY = 1000
GRAPH = "partition graph"
RENDER = "partition render"
CLUSTERS = "partition clusters"


@dataclass(frozen=True)
class Tally:
    """A stage's name and the label of what it counts, logged every ``every`` items and once when done."""

    stage: str
    label: str
    every: int = PROGRESS_EVERY
