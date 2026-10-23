"""The barrier that blocks a statement linking one field to many."""

from __future__ import annotations

from collections import Counter
from collections.abc import Set
from dataclasses import dataclass

from cobble.experimental.partition.barrier import Barrier
from cobble.experimental.partition.field_leaf import FieldLeaf


@dataclass(frozen=True)
class FanoutBarrier(Barrier):
    """Blocks a statement when any one field it links has more than ``limit`` partner fields; a table's occurrences are one."""

    limit: int

    @property
    def name(self) -> str:
        return f"fanout-{self.limit}"

    def blocks(self, pairs: Set[tuple[FieldLeaf, FieldLeaf]]) -> bool:
        outward = {(s.node, t.declared) for s, t in pairs}
        inward = {(s.declared, t.node) for s, t in pairs}
        partners = Counter(("source", s) for s, _ in outward) + Counter(
            ("target", t) for _, t in inward
        )
        return any(count > self.limit for count in partners.values())
