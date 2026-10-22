"""The field graph as one value."""

from __future__ import annotations

from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from pydantic import BaseModel, ConfigDict


class FieldGraph(BaseModel):
    """Every node and edge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @property
    def barrier(self) -> str:
        return ", ".join(sorted({edge.barrier for edge in self.edges}))
