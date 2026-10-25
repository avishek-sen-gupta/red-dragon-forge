"""The attributes the fixpoint writes on a FLOWS_TO edge."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FlowAttrs(BaseModel):
    """Where one value moved: its statement, both extents, and its origin when it is not storage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node: str
    source_extent: str
    target_extent: str
    origin: str
    literal: str
