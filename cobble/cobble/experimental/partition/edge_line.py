"""One edge of the field graph, as one line of the graph file."""

from __future__ import annotations

from cobble.experimental.partition.graph_edge import GraphEdge
from pydantic import BaseModel, ConfigDict


class EdgeLine(BaseModel):
    """A graph file line holding an edge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge: GraphEdge
