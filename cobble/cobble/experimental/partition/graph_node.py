"""One node of the field graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from cobble.dataflow.fields.origin import NO_ORIGIN, Origin
from cobble.dataflow.fields.sink import NO_SINK, Sink
from cobble.experimental.partition.node_kind import NodeKind
from pydantic import ConfigDict, Field


def _storage(origin: Origin) -> bool:
    return origin.is_storage


def _no_sink(sink: Sink) -> bool:
    return sink.is_none


@dataclass(frozen=True, slots=True)
class GraphNode:
    """An elementary field (one occurrence of a table element), a program's typed origin or sink, or a dataset slot starting at ``offset`` in its record."""

    id: str
    kind: NodeKind
    label: str
    program: str
    record: str = ""
    pic: str = ""
    field: str = ""
    subscripts: tuple[int, ...] = ()
    size: int = 0
    offset: int = 0
    origin: Annotated[Origin, Field(exclude_if=_storage)] = NO_ORIGIN
    sink: Annotated[Sink, Field(exclude_if=_no_sink)] = NO_SINK
    __pydantic_config__ = ConfigDict(extra="forbid")
