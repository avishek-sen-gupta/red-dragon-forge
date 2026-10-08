"""One program as the area-need rounds see it: built once, its ASG and layout let go."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.demand_parts import DemandParts, Slots
from cobble.dataflow.fixpoint.live_graph import LiveGraph
from cobble.dataflow.fixpoint.places import Places
from cobble.dataflow.fixpoint.site_answer import SiteAnswer


@dataclass(frozen=True)
class PreparedProgram:
    """The member, its liveness graph and demand parts, the entry node, the received areas by
    slot, each returning call's site and handed-over areas by slot, the dynamic sites
    it resolves on its own with the programs they reach, those it cannot with why, and
    where its nodes sit."""

    member: str
    graph: LiveGraph
    parts: DemandParts
    entry: str
    received: Slots
    returning: tuple[tuple[str, CallSite, Slots], ...]
    sites: tuple[tuple[str, tuple[str, ...]], ...]
    unresolved: tuple[tuple[str, SiteAnswer], ...]
    places: Places
