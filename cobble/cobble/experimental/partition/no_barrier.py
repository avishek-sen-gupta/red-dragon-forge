"""The barrier that blocks nothing: clusters over the raw graph."""

from __future__ import annotations

from collections.abc import Set

from cobble.experimental.partition.barrier import Barrier
from cobble.experimental.partition.field_leaf import FieldLeaf


class NoBarrier(Barrier):
    """Every crossing is clustered."""

    @property
    def name(self) -> str:
        return "none"

    def blocks(self, pairs: Set[tuple[FieldLeaf, FieldLeaf]]) -> bool:
        return False
