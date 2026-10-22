"""Everything the page's script reads."""

from __future__ import annotations

from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.page_node import PageNode
from pydantic import BaseModel, ConfigDict


class PageData(BaseModel):
    """The drawn nodes and the graph's edges."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    barrier: str
    nodes: tuple[PageNode, ...]
    edges: tuple[GraphEdge, ...]
