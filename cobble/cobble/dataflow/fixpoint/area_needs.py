"""One program's share of the corpus-wide area need: what it reads of what it is handed."""

from __future__ import annotations

from functools import reduce

from cobble.dataflow.fields.aliases import received_areas
from cobble.dataflow.fields.program_layout import ProgramLayout
from cobble.dataflow.fields.spans import Spans, spans_of
from cobble.dataflow.fixpoint.area_need import AreaNeed, joined, relative
from cobble.dataflow.fixpoint.fixpoint import entry_of, program_graph
from cobble.dataflow.fixpoint.liveness import graph_of, live_sets
from cobble.dataflow.fixpoint.prepared_program import PreparedProgram
from cobble.dataflow.jumps.discover import call_areas, demand_parts, returns
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent


def prepared(asg: CobolASG, layout: ProgramLayout) -> PreparedProgram:
    """Everything the rounds need, built from the ASG once."""
    cfg, statements = program_graph(asg)
    index = layout.index
    return PreparedProgram(
        graph=graph_of(cfg, statements, index),
        parts=demand_parts(asg, cfg, statements, index),
        entry=entry_of(asg),
        received=received_areas(asg, index),
        returning=tuple(
            (node.id, call_areas(node, index))
            for node in cfg.nodes
            if node.transfer in CALL_TRANSFERS and returns(node)
        ),
    )


def need_found(program: PreparedProgram, need: AreaNeed) -> AreaNeed:
    """The received bytes this program's targets depend on at entry, and the bytes
    of each area it hands to a LINK or CALL that it reads again afterwards, given
    what the rest of the corpus is known to need so far."""
    sets = live_sets(program.graph, program.parts.demand(need))
    rank = {node: position for position, node in enumerate(program.graph.order)}
    at_entry = spans_of(sets[rank[program.entry]]) if program.entry in rank else {}
    entry = AreaNeed(
        entry=tuple(
            (position, bounds)
            for position, area in program.received
            for bounds in (relative(at_entry, area),)
            if bounds
        )
    )
    return reduce(
        joined,
        (
            AreaNeed(back=((position, bounds),))
            for node, areas in program.returning
            for after in (_after(program, sets, rank[node]),)
            for position, area in areas
            for bounds in (relative(after, area),)
            if bounds
        ),
        entry,
    )


def _after(
    program: PreparedProgram,
    sets: tuple[frozenset[FieldExtent], ...],
    position: int,
) -> Spans:
    return spans_of(
        extent
        for successor in program.graph.successors[position]
        for extent in sets[successor]
    )
