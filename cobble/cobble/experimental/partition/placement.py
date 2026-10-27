"""Where the page starts every node, and each program's patch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.experimental.partition.page_region import PageRegion


@dataclass(frozen=True)
class Placement:
    """Each node's starting point and each program's patch."""

    points: Mapping[str, tuple[float, float]]
    regions: tuple[PageRegion, ...]
