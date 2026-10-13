"""One host-variable field of a generated DCLGEN record, as the copybook renders it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DclgenField:
    host_var: str
    category: str
    length: int
    pic: str
