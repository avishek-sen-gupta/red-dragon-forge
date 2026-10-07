"""One program as the area-need rounds see it: built once, its ASG and layout let go."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.demand_parts import DemandParts
from cobble.dataflow.fixpoint.live_graph import LiveGraph
from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class PreparedProgram:
    """The liveness graph and demand parts, the entry node, the received areas by
    position, and each returning call's handed-over areas by position."""

    graph: LiveGraph
    parts: DemandParts
    entry: str
    received: tuple[tuple[int, FieldExtent], ...]
    returning: tuple[tuple[str, tuple[tuple[int, FieldExtent], ...]], ...]
