"""One line of unified.jsonl: the graph fields that hold one datum."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UnifiedLine(BaseModel):
    """A class of field nodes, sorted; the first names the class."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    members: tuple[str, ...]
