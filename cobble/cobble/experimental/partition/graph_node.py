"""One node of the field graph."""

from __future__ import annotations

from cobble.experimental.partition.node_kind import NodeKind
from pydantic import BaseModel, ConfigDict


class GraphNode(BaseModel):
    """An elementary field (one occurrence of a table element), or a program's origin or sink."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: NodeKind
    label: str
    program: str
    record: str = ""
    pic: str = ""
    field: str = ""
    subscripts: tuple[int, ...] = ()
    size: int = 0
