"""One node of the field graph, as one line of the graph file."""

from __future__ import annotations

from cobble.experimental.partition.graph_node import GraphNode
from pydantic import BaseModel, ConfigDict


class NodeLine(BaseModel):
    """A graph file line holding a node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node: GraphNode
