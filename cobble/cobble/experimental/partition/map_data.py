"""The program map as the page draws it."""

from __future__ import annotations

from cobble.experimental.partition.map_edge import MapEdge
from cobble.experimental.partition.map_node import MapNode
from pydantic import BaseModel, ConfigDict


class MapData(BaseModel):
    """Every program and dataset record, and every pair of them some graph edge links."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[MapNode, ...]
    edges: tuple[MapEdge, ...]
