"""The field graph as one value, and as the file the graph stage writes."""

from __future__ import annotations

from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from pydantic import BaseModel, ConfigDict


class FieldGraph(BaseModel):
    """Every node and edge, and the barrier that decided which edges clustering crosses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    barrier: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
