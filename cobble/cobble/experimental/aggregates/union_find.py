"""Disjoint-set / union-find over arbitrary hashable keys."""

from __future__ import annotations

from collections import defaultdict


class UnionFind:
    """Path-compressed union-find with union by rank."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: str, y: str) -> bool:
        """Merge the sets containing *x* and *y*.  Returns True if a merge happened."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1
        return True

    def classes(self) -> dict[str, list[str]]:
        """Return ``{representative: sorted_members}`` for every set."""
        groups: dict[str, list[str]] = defaultdict(list)
        for x in self._parent:
            groups[self.find(x)].append(x)
        return {k: sorted(v) for k, v in groups.items()}
