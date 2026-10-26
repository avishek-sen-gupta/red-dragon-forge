"""A graph file line holding an edge, read as unify needs it."""

from __future__ import annotations

from cobble.experimental.aggregates.byte_edge import ByteEdge
from pydantic import BaseModel, ConfigDict


class ByteEdgeLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    edge: ByteEdge
