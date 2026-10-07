"""The byte ranges whose facts a walk must answer exactly, by the node they are read at."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class Demand:
    """Every node a fact is read at, and the extents read there."""

    at: Mapping[str, frozenset[FieldExtent]] = MappingProxyType({})
