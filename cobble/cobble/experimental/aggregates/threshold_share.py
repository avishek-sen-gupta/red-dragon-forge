"""One threshold's admitted columns, its unified-class columns, and their share of the entries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdShare:
    """A threshold, the columns it admits, how many of them are unified classes, and the classes' share of those columns' entries."""

    min_occurrences: int
    columns: int
    class_columns: int
    share: float
