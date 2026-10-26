"""A graph file line holding a node, read as unify needs it."""

from __future__ import annotations

from cobble.experimental.aggregates.byte_node import ByteNode
from pydantic import BaseModel, ConfigDict


class ByteNodeLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node: ByteNode
