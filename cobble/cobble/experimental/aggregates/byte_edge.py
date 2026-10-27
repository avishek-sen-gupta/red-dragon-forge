"""A graph edge as unify reads it: its ends, where its bytes land and how sure a dataset edge is and why, and whether its statements rebuilt the target in place, the rest of the line ignored."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.certainty import Certainty
from pydantic import ConfigDict


@dataclass(frozen=True, slots=True)
class ByteEdge:
    source: str
    target: str
    alignments: tuple[ByteAlignment, ...] = ()
    aligned: bool = False
    certainty: Certainty = Certainty.EXACT
    reasons: tuple[str, ...] = ()
    rebuilt: bool = False
    __pydantic_config__ = ConfigDict(extra="ignore")
