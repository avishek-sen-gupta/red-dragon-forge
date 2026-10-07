"""One program's share of the corpus-wide area need: what it reads of what it is handed."""

from __future__ import annotations

from functools import reduce

from cobble.dataflow.fields.aliases import received_areas
from cobble.dataflow.fields.program_layout import ProgramLayout
from cobble.dataflow.fields.spans import NO_SPANS, Spans, union
from cobble.dataflow.fixpoint.area_need import AreaNeed, joined, relative
from cobble.dataflow.fixpoint.fixpoint import entry_of, program_graph
from cobble.dataflow.fixpoint.live import Live
from cobble.dataflow.fixpoint.liveness import live as live_ranges
from cobble.dataflow.jumps.discover import call_areas, call_target_demand, returns
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_asg.asg_types import CobolASG


def _after(cfg: Cfg, live: Live, node: str) -> Spans:
    return reduce(
        union,
        (live.entry.get(edge.target, NO_SPANS) for edge in cfg.successors(node)),
        NO_SPANS,
    )


def need_found(asg: CobolASG, layout: ProgramLayout, need: AreaNeed) -> AreaNeed:
    """The received bytes this program's targets depend on at entry, and the bytes
    of each area it hands to a LINK or CALL that it reads again afterwards, given
    what the rest of the corpus is known to need so far."""
    cfg, statements = program_graph(asg)
    index = layout.index
    live = live_ranges(
        cfg, statements, index, call_target_demand(asg, cfg, statements, index, need)
    )
    at_entry = live.entry.get(entry_of(asg), NO_SPANS)
    entry = AreaNeed(
        entry=tuple(
            (position, bounds)
            for position, area in received_areas(asg, index)
            for bounds in (relative(at_entry, area),)
            if bounds
        )
    )
    return reduce(
        joined,
        (
            AreaNeed(back=((position, bounds),))
            for node in cfg.nodes
            if node.transfer in CALL_TRANSFERS and returns(node)
            for position, area in call_areas(node, index)
            for bounds in (relative(_after(cfg, live, node.id), area),)
            if bounds
        ),
        entry,
    )
