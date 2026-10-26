"""A graph node as unify reads it: a field's or dataset slot's id, program, size and subscripts, the rest of the line ignored."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.experimental.partition.node_kind import NodeKind
from pydantic import ConfigDict


@dataclass(frozen=True, slots=True)
class ByteNode:
    id: str
    kind: NodeKind
    program: str
    subscripts: tuple[int, ...] = ()
    size: int = 0
    __pydantic_config__ = ConfigDict(extra="ignore")
