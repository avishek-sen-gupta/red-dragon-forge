"""What the coordinator asks the area-need workers once the rounds settle."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.area_table import AreaTable


@dataclass(frozen=True)
class ExplainRequest:
    """Explain every held member whose settled entry need is at least ``over`` bytes."""

    table: AreaTable
    over: int
