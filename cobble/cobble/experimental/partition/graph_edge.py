"""One directed edge of the field graph."""

from __future__ import annotations

from cobble.experimental.partition.byte_alignment import ByteAlignment
from pydantic import BaseModel, ConfigDict


class GraphEdge(BaseModel):
    """Bytes moving from source to target, at how many sites, whether the named barrier lets clustering cross it, and where the bytes land: ``aligned`` when every site's placement is known."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    sites: int
    clustered: bool
    cross_program: bool
    barrier: str
    alignments: tuple[ByteAlignment, ...] = ()
    aligned: bool = False
