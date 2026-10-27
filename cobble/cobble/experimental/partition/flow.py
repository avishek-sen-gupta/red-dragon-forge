"""One statement's movement of bytes from one node to another."""

from __future__ import annotations

from dataclasses import dataclass, field

from cobble.experimental.partition.byte_alignment import ByteAlignment


@dataclass(frozen=True, order=True)
class Flow:
    """Bytes from source to target at a site, whether the barrier let clustering cross it, the bytes' places when known, and whether the statement rebuilt the target in place; ordered by its ends first."""

    source: str
    target: str
    site: str
    clustered: bool
    alignment: tuple[ByteAlignment, ...] = field(default=(), compare=False)
    rebuilt: bool = field(default=False, compare=False)
