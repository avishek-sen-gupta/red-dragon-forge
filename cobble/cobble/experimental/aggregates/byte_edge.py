"""A graph edge as unify reads it: its ends and where its bytes land, the rest of the line ignored."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.experimental.partition.byte_alignment import ByteAlignment
from pydantic import ConfigDict


@dataclass(frozen=True, slots=True)
class ByteEdge:
    source: str
    target: str
    alignments: tuple[ByteAlignment, ...] = ()
    aligned: bool = False
    __pydantic_config__ = ConfigDict(extra="ignore")
