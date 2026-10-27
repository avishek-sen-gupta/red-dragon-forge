"""How the extents stage runs: its workers, and whether it declares what a program uses but never declares."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtentsOptions:
    """Worker processes, and ``undeclared``: declare every field name a program uses
    but never declares, as when its copybook is missing."""

    max_workers: int = 1
    undeclared: bool = False
