"""One directed edge of the field graph."""

from __future__ import annotations

from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.certainty import Certainty
from pydantic import BaseModel, ConfigDict


class GraphEdge(BaseModel):
    """Bytes moving from source to target, at how many sites, whether the named barrier lets clustering cross it, and where the bytes land: ``aligned`` when every site's placement is known, and how sure a dataset edge is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    sites: int
    clustered: bool
    cross_program: bool
    barrier: str
    alignments: tuple[ByteAlignment, ...] = ()
    aligned: bool = False
    certainty: Certainty = Certainty.EXACT
    reasons: tuple[str, ...] = ()
