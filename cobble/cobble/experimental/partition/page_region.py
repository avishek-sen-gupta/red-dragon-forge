"""One program's patch on the page."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PageRegion(BaseModel):
    """Where a program's patch is centred and how far its fields may spread; the page lays its fields out inside it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str
    x: float
    y: float
    radius: float
