"""Which bytes of an edge's source land on which bytes of its target."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ByteAlignment(BaseModel):
    """``length`` bytes from offset ``source`` in the source field to offset ``target`` in the target field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: int
    target: int
    length: int
