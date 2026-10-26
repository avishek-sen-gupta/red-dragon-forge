"""One node of the program map."""

from __future__ import annotations

from cobble.experimental.partition.map_kind import MapKind
from pydantic import BaseModel, ConfigDict


class MapNode(BaseModel):
    """A program or dataset record, where it is drawn, how many graph nodes it holds, and the page a program links to (empty for a dataset)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: MapKind
    label: str
    x: float
    y: float
    fields: int
    href: str
