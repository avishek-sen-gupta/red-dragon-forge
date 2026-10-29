"""One link the combine used, as links.jsonl stores it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LinkRow(BaseModel):
    """A crossing between two programs and the windows it binds."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    caller: str
    node: str
    transfer: str
    callee: str
    caller_extent: str
    callee_extent: str
    returns: bool
    reason: str
