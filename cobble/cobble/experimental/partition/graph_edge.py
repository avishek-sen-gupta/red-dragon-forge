"""One directed edge of the field graph."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GraphEdge(BaseModel):
    """Bytes moving from source to target, at how many sites, and whether the named barrier lets clustering cross it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    sites: int
    clustered: bool
    cross_program: bool
    barrier: str
