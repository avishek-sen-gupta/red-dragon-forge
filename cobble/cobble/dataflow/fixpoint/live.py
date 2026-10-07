"""Which byte ranges are live on entry to each node, as merged spans per region."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cobble.dataflow.fields.spans import NO_SPANS, Spans, overlaps
from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class Live:
    """Live spans per node; ``everything`` keeps every extent at every node."""

    entry: Mapping[str, Spans] = MappingProxyType({})
    everything: bool = False

    def keeps(self, node: str, extent: FieldExtent) -> bool:
        return self.everything or overlaps(self.entry.get(node, NO_SPANS), extent)


EVERYTHING = Live(everything=True)
