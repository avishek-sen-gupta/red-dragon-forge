"""One program's report in an area-need round, and the table a round's reports resolve to."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import reduce
from itertools import groupby
from operator import itemgetter

from cobble.dataflow.fields.program_layout import ProgramLayout
from cobble.dataflow.fields.spans import Spans, spans_of
from cobble.dataflow.fixpoint.area_found import AreaFound
from cobble.dataflow.fixpoint.area_need import AreaNeed, Bounds, joined, relative
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.area_table import AreaTable, Receives, area_table
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.fixpoint import entry_of, program_graph
from cobble.dataflow.fixpoint.liveness import graph_of, live_sets
from cobble.dataflow.fixpoint.local_sites import local_sites
from cobble.dataflow.fixpoint.places import places_of
from cobble.dataflow.fixpoint.prepared_program import PreparedProgram
from cobble.dataflow.fixpoint.site_answer import SiteAnswer
from cobble.dataflow.fixpoint.site_row import SiteRow
from cobble.dataflow.fixpoint.site_row_definition import SiteRowDefinition
from cobble.dataflow.fixpoint.target_site import Sites
from cobble.dataflow.jumps.discover import (
    call_areas,
    call_site,
    demand_parts,
    received_slots,
    returns,
)
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent


def prepared(
    member: str, asg: CobolASG, layout: ProgramLayout, programs: Mapping[str, str]
) -> tuple[PreparedProgram, tuple[SiteRow, ...]]:
    """Everything the rounds and a report need, built from the ASG once, and a row
    for each of its dynamic sites. ``programs`` maps a transaction id to the program
    the CSD runs for it."""
    cfg, statements = program_graph(asg)
    index = layout.index
    parts = demand_parts(asg, cfg, statements, index)
    returning = tuple(
        (node.id, call_site(node), call_areas(node, index))
        for node in cfg.nodes
        if node.transfer in CALL_TRANSFERS and returns(node)
    )
    entry = entry_of(asg)
    calls = (
        *((node, site) for node, site, _ in parts.entry),
        *((node, site) for node, site, _ in returning),
    )
    answers = local_sites(
        cfg, statements, index, layout.records, entry, calls, programs
    )
    places = places_of(cfg, tuple(sorted({node for node, _ in calls})))
    program = PreparedProgram(
        member=member,
        graph=graph_of(cfg, statements, index),
        parts=parts,
        entry=entry,
        received=received_slots(asg, index),
        returning=returning,
        sites=tuple(
            (node, answer.callees) for node, answer in answers if answer.callees
        ),
        unresolved=tuple(
            (node, replace(answer, definitions=()))
            for node, answer in answers
            if not answer.callees
        ),
        places=places,
    )
    return program, _site_rows(program, answers)


def _site_rows(
    program: PreparedProgram, answers: tuple[tuple[str, SiteAnswer], ...]
) -> tuple[SiteRow, ...]:
    rank = {node: position for position, node in enumerate(program.graph.order)}
    return tuple(
        SiteRow(
            member=program.member,
            place=program.places.at(rank[node]),
            transfer=program.places.transfer(node),
            operand=answer.operand,
            callees=answer.callees,
            reasons=tuple(doubt.value for doubt in answer.doubts),
            definitions=tuple(
                SiteRowDefinition(
                    place=program.places.at(rank[one.node]),
                    kind=one.kind,
                    values=one.values,
                    sources=one.sources,
                    reasons=one.reasons,
                )
                for one in answer.definitions
            ),
        )
        for node, answer in answers
    )


def need_found(program: PreparedProgram, table: AreaTable) -> AreaFound:
    """The received bytes this program's targets depend on at entry, and the bytes
    of each area it hands to a LINK or CALL that it reads again afterwards, given
    what the table says its callees read and its callers read back."""
    seen = table.seen_from(program.member)
    sets = live_sets(program.graph, program.parts.demand(seen))
    rank = {node: position for position, node in enumerate(program.graph.order)}
    at_entry = spans_of(sets[rank[program.entry]]) if program.entry in rank else {}
    return AreaFound(
        member=program.member,
        entry=reduce(
            joined,
            (
                AreaNeed(entry=((slot, bounds),))
                for slot, area in program.received
                for bounds in (relative(at_entry, area),)
                if bounds
            ),
            AreaNeed(),
        ),
        read_backs=tuple(
            (reached, slot, bounds)
            for node, site, areas in program.returning
            for after in (_after(program, sets, rank[node]),)
            for slot, area in areas
            for bounds in (relative(after, area),)
            if bounds
            for reached in _reached(seen, node, site)
        ),
    )


def _reached(table: AreaTable, node: str, site: CallSite) -> tuple[CallSite, ...]:
    """The call as each program it can reach, or as itself when none is known."""
    callees = table.callees_at(node, site)
    if not callees:
        return (site,)
    return tuple(CallSite(callee, site.kind) for callee in callees)


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


def _backs(pairs: Sequence[tuple[AreaSlot, Bounds]]) -> AreaNeed:
    return reduce(
        joined, (AreaNeed(back=((slot, bounds),)) for slot, bounds in pairs), AreaNeed()
    )


def resolved(found: Sequence[AreaFound], receives: Receives, sites: Sites) -> AreaTable:
    """Each member's own entry need, and as its back need what the calls that can
    reach it read back, with what every unresolved dynamic call reads back."""
    dynamic = _backs(
        tuple(
            (slot, bounds)
            for one in found
            for site, slot, bounds in one.read_backs
            if site.dynamic
        )
    )
    named = sorted(
        (site.callee, slot, bounds)
        for one in found
        for site, slot, bounds in one.read_backs
        if not site.dynamic
    )
    static = {
        callee: _backs(tuple((slot, bounds) for _, slot, bounds in group))
        for callee, group in groupby(named, itemgetter(0))
    }
    return area_table(
        tuple(
            (
                one.member,
                AreaNeed(
                    entry=one.entry.entry,
                    back=joined(static.get(one.member, AreaNeed()), dynamic).back,
                ),
            )
            for one in found
        ),
        receives,
        sites,
        dynamic.back,
    )
