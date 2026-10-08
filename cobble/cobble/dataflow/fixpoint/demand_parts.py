"""Each node's demand, split into what never changes and the handed-over areas a need narrows."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.area_table import AreaTable
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.demand import Demand
from cobol_memory.field_extent import FieldExtent

Slots = tuple[tuple[AreaSlot, FieldExtent], ...]


@dataclass(frozen=True)
class DemandParts:
    """Per node: extents always demanded, areas handed over with the call that hands
    them (narrowed by what that callee reads on entry), and areas received (narrowed
    by what this member's callers read back)."""

    local: tuple[tuple[str, tuple[FieldExtent, ...]], ...] = ()
    entry: tuple[tuple[str, CallSite, Slots], ...] = ()
    back: tuple[tuple[str, Slots], ...] = ()

    def demand(self, table: AreaTable) -> Demand:
        pieces = (
            *((node, extent) for node, extents in self.local for extent in extents),
            *(
                (node, piece)
                for node, site, areas in self.entry
                for slot, area in areas
                for piece in table.entry_at(site, slot, area)
            ),
            *(
                (node, piece)
                for node, areas in self.back
                for slot, area in areas
                for piece in table.back_at(slot, area)
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
