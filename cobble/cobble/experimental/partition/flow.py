"""One statement's movement of bytes from one node to another."""

from __future__ import annotations

from dataclasses import dataclass, field

from cobble.experimental.partition.byte_alignment import ByteAlignment


@dataclass(frozen=True, order=True)
class Flow:
    """Bytes from source to target at a site, whether the barrier let clustering cross it, and the bytes' places when known; ordered by its ends first."""

    source: str
    target: str
    site: str
    clustered: bool
    alignment: tuple[ByteAlignment, ...] = field(default=(), compare=False)
