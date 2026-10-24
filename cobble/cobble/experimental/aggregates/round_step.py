"""One round of the decomposition: which fields it factors and into how many factors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoundStep:
    """The fewest paragraphs a field must be written in to enter this round, and the round's factor count."""

    min_occurrences: int
    k: int
