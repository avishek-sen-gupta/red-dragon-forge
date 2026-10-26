"""One edge of the program map."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MapEdge(BaseModel):
    """Two map nodes, ``source < target``, and how many graph edges link them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    links: int
