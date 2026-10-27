"""Everything the page's script reads."""

from __future__ import annotations

from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.page_node import PageNode
from cobble.experimental.partition.page_region import PageRegion
from pydantic import BaseModel, ConfigDict


class PageData(BaseModel):
    """The drawn nodes, the graph's edges, and each program's patch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    barrier: str
    nodes: tuple[PageNode, ...]
    edges: tuple[GraphEdge, ...]
    regions: tuple[PageRegion, ...]
