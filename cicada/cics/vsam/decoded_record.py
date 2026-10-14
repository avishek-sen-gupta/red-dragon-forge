"""A record decoded through its copybook: each field's name and decoded value, in layout order."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TypeAlias

Leaf: TypeAlias = str | int | float


@dataclass(frozen=True, eq=False)
class DecodedRecord(Mapping[str, "Decoded"]):
    fields: tuple[tuple[str, Decoded], ...]

    def __getitem__(self, name: str) -> Decoded:
        return dict(self.fields)[name]

    def __iter__(self) -> Iterator[str]:
        return (name for name, _ in self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def plain(self) -> dict[str, Decoded]:
        return dict(self.fields)


Decoded: TypeAlias = Leaf | tuple[Leaf, ...] | DecodedRecord | tuple[DecodedRecord, ...]
