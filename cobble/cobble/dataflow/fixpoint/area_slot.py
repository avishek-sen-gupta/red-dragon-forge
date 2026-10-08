"""Where a handed-over area sits among what a program receives."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.area_kind import AreaKind


@dataclass(frozen=True, order=True)
class AreaSlot:
    """The kind of area, and its parameter position: always 0 for a commarea."""

    kind: AreaKind
    position: int
