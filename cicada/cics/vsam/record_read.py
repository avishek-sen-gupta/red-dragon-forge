"""A CICS file read that returned a record, with the EIBRESP it raised."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecordRead:
    record: bytes
    resp: int
