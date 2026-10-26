"""The field and dataset-slot nodes and every edge of a partition graph, as unify reads them."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.experimental.aggregates.byte_edge import ByteEdge
from cobble.experimental.aggregates.byte_node import ByteNode


@dataclass(frozen=True)
class ByteGraph:
    nodes: tuple[ByteNode, ...]
    edges: tuple[ByteEdge, ...]
