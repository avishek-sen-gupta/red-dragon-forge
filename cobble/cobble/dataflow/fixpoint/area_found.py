"""One program's report from an area-need round: what it reads on entry, and after each call."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.area_need import AreaNeed, Bounds
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.call_site import CallSite


@dataclass(frozen=True)
class AreaFound:
    """``entry`` holds only entry bounds; ``read_backs`` the bytes of each area handed
    to a returning call that are read after it returns."""

    member: str
    entry: AreaNeed
    read_backs: tuple[tuple[CallSite, AreaSlot, Bounds], ...] = ()
