"""The strategy deciding which crossings clustering must not cross."""

from __future__ import annotations

from collections.abc import Set
from typing import Protocol

from cobble.experimental.partition.field_leaf import FieldLeaf


class Barrier(Protocol):
    """Judges the field pairs one statement links."""

    @property
    def name(self) -> str: ...

    def blocks(self, pairs: Set[tuple[FieldLeaf, FieldLeaf]]) -> bool: ...
