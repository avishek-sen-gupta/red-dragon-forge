"""The barrier that blocks a statement linking one field to many."""

from __future__ import annotations

from collections import Counter
from collections.abc import Set
from dataclasses import dataclass

from cobble.experimental.partition.barrier import Barrier


@dataclass(frozen=True)
class FanoutBarrier(Barrier):
    """Blocks a statement when any one field it links has more than ``limit`` partners."""

    limit: int

    @property
    def name(self) -> str:
        return f"fanout-{self.limit}"

    def blocks(self, pairs: Set[tuple[str, str]]) -> bool:
        partners = Counter(("source", s) for s, _ in pairs) + Counter(
            ("target", t) for _, t in pairs
        )
        return any(count > self.limit for count in partners.values())
