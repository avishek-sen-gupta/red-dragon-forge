"""The barrier that blocks nothing: clusters over the raw graph."""

from __future__ import annotations

from collections.abc import Set

from cobble.experimental.partition.barrier import Barrier


class NoBarrier(Barrier):
    """Every crossing is clustered."""

    @property
    def name(self) -> str:
        return "none"

    def blocks(self, pairs: Set[tuple[str, str]]) -> bool:
        return False
