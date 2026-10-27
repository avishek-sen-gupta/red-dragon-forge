"""The attributes the fixpoint writes on a FLOWS_TO edge."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FlowAttrs(BaseModel):
    """Where one value moved: its statement, both extents, its origin when it is not storage, and
    where its source's first byte landed in the target when the bytes moved unchanged, and whether
    the statement rebuilt the target in place (arithmetic, STRING)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node: str
    source_extent: str
    target_extent: str
    origin: str
    literal: str
    landing: tuple[int, ...]
    rebuilt: bool
