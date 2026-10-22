"""One node as the page draws it."""

from __future__ import annotations

from cobble.experimental.partition.node_kind import NodeKind
from pydantic import BaseModel, ConfigDict


class PageNode(BaseModel):
    """A node with its position, its component and cluster (-1 for none), and its degree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: NodeKind
    label: str
    program: str
    record: str
    pic: str
    x: float
    y: float
    component: int
    cluster: int
    degree: int
