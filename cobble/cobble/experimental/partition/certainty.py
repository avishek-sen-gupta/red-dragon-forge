"""How sure a dataset link is."""

from __future__ import annotations

from enum import StrEnum


class Certainty(StrEnum):
    """``exact`` when every step from site to dataset is proven; ``possible`` carries reasons."""

    EXACT = "exact"
    POSSIBLE = "possible"
