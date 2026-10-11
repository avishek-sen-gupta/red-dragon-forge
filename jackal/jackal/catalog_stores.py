"""The catalog's in-place stores: one lookup table, written and read back by the same DatasetCatalog."""

from __future__ import annotations

from collections.abc import Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class Table(Generic[K, V]):
    def __init__(self) -> None:
        self._rows: dict[K, V] = {}

    def has(self, name: K) -> bool:
        return name in self._rows

    def get(self, name: K) -> V:
        return self._rows[name]

    def put(self, name: K, value: V) -> V:
        self._rows[name] = value
        return value

    def take(self, name: K) -> V:
        return self._rows.pop(name)

    def values(self) -> tuple[V, ...]:
        return tuple(self._rows.values())

    def drain(self) -> tuple[V, ...]:
        values = tuple(self._rows.values())
        self._rows.clear()
        return values
