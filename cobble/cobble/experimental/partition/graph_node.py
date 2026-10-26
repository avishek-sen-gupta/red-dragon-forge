"""One node of the field graph."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.experimental.partition.node_kind import NodeKind
from pydantic import ConfigDict


@dataclass(frozen=True, slots=True)
class GraphNode:
    """An elementary field (one occurrence of a table element), a program's origin or sink, or a dataset slot starting at ``offset`` in its record."""

    id: str
    kind: NodeKind
    label: str
    program: str
    record: str = ""
    pic: str = ""
    field: str = ""
    subscripts: tuple[int, ...] = ()
    size: int = 0
    offset: int = 0
    __pydantic_config__ = ConfigDict(extra="forbid")
