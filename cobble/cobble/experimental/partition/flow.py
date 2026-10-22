"""One statement's movement of bytes from one node to another."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Flow:
    """Bytes from source to target at a site, and whether the barrier let clustering cross it; ordered by its ends first."""

    source: str
    target: str
    site: str
    clustered: bool
