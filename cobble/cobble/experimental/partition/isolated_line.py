"""One field in no cluster, as one line of the clusters file."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IsolatedLine(BaseModel):
    """A clusters file line naming a field no cluster holds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    isolated: str
