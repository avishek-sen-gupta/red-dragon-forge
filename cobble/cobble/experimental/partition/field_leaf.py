"""One extent of an elementary field."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldLeaf:
    """An elementary field's bytes in one region; each occurrence of a table is its own node."""

    program: str
    record: str
    name: str
    region: str
    start: int
    end: int
    pic: str
    path: tuple[str, ...]
    subscripts: tuple[int, ...]

    @property
    def subscript(self) -> str:
        if not self.subscripts:
            return ""
        return f"({','.join(str(i) for i in self.subscripts)})"

    @property
    def occurrence(self) -> str:
        return f"{self.name}{self.subscript}"

    @property
    def declared(self) -> str:
        return f"{self.program}:{self.record}.{self.name}"

    @property
    def node(self) -> str:
        return f"{self.declared}{self.subscript}"

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end
