"""The strategy deciding which crossings clustering must not cross."""

from __future__ import annotations

from collections.abc import Set
from typing import Protocol


class Barrier(Protocol):
    """Judges the field pairs one statement links."""

    @property
    def name(self) -> str: ...

    def blocks(self, pairs: Set[tuple[str, str]]) -> bool: ...
