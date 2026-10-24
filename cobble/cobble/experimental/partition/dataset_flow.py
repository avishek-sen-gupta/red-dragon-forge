"""One site's movement of bytes between a field and a dataset slot."""

from __future__ import annotations

from dataclasses import dataclass, field

from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.certainty import Certainty


@dataclass(frozen=True, order=True)
class DatasetFlow:
    """A field-to-slot (write) or slot-to-field (read) flow at a site, how sure it is and why, and where the bytes land when exact; ordered by its ends first."""

    source: str
    target: str
    site: str
    certainty: Certainty
    reasons: tuple[str, ...]
    alignment: tuple[ByteAlignment, ...] = field(compare=False)
