"""One extent of an elementary field."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldLeaf:
    """An elementary field's bytes in one region; every occurrence of a table shares one node."""

    program: str
    record: str
    name: str
    region: str
    start: int
    end: int
    pic: str
    path: tuple[str, ...]

    @property
    def node(self) -> str:
        return f"{self.program}:{self.record}.{self.name}"

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end
