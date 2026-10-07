"""Each node's demand, split into what never changes and the handed-over areas a need narrows."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from cobble.dataflow.fixpoint.area_need import AreaNeed
from cobble.dataflow.fixpoint.demand import Demand
from cobol_memory.field_extent import FieldExtent

_Areas = tuple[tuple[int, FieldExtent], ...]


@dataclass(frozen=True)
class DemandParts:
    """Per node: extents always demanded, areas handed over (narrowed by what callees
    read on entry), and areas received (narrowed by what callers read back)."""

    local: tuple[tuple[str, tuple[FieldExtent, ...]], ...] = ()
    entry: tuple[tuple[str, _Areas], ...] = ()
    back: tuple[tuple[str, _Areas], ...] = ()

    def demand(self, need: AreaNeed) -> Demand:
        pieces = (
            *((node, extent) for node, extents in self.local for extent in extents),
            *(
                (node, piece)
                for node, areas in self.entry
                for position, area in areas
                for piece in need.at_entry(position, area)
            ),
            *(
                (node, piece)
                for node, areas in self.back
                for position, area in areas
                for piece in need.read_back(position, area)
            ),
        )
        nodes = {node for node, _ in pieces}
        return Demand(
            at=MappingProxyType(
                {
                    node: frozenset(extent for at, extent in pieces if at == node)
                    for node in nodes
                }
            )
        )
