"""Where a key sits in a record: its offset from the record's start, and its length."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecordKey:
    offset: int
    length: int
