"""What the graph's dataset slots link, and what kept each linked field out of a class."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotFields:
    """Field and slot counts, dataset edges by certainty, the possible ones counted per reason, most common first, and the fields exact edges link split into classed, blocked by an unplaced edge, and neither; plus fields only possible edges link."""

    fields: int
    slots: int
    exact_edges: int
    possible_edges: int
    reasons: tuple[tuple[str, int], ...]
    linked: int
    classed: int
    blocked: int
    possible_only: int
