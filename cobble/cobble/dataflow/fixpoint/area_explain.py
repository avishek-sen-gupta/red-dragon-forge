"""Why one member needs the received bytes it does, as one row: each demand source alone, and the writes that widen."""

from __future__ import annotations

from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.spans import pairs_of, spans_of
from cobble.dataflow.fixpoint.area_need import relative
from cobble.dataflow.fixpoint.area_table import AreaTable
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.demand_parts import DemandParts
from cobble.dataflow.fixpoint.explain_row import ExplainRow
from cobble.dataflow.fixpoint.explain_site import ExplainSite
from cobble.dataflow.fixpoint.explain_source import ExplainSource
from cobble.dataflow.fixpoint.explain_source_kind import ExplainSourceKind
from cobble.dataflow.fixpoint.explain_widening import ExplainWidening
from cobble.dataflow.fixpoint.live_write import LiveWrite
from cobble.dataflow.fixpoint.liveness import live_sets, needed_sources, strong
from cobble.dataflow.fixpoint.prepared_program import PreparedProgram
from cobble.dataflow.fixpoint.site_resolution import SiteResolution
from cobol_memory.field_extent import FieldExtent

_Sets = tuple[frozenset[FieldExtent], ...]
_WIDEST = 20


def _entry_bytes(program: PreparedProgram, sets: _Sets) -> int:
    rank = {node: position for position, node in enumerate(program.graph.order)}
    at_entry = spans_of(sets[rank[program.entry]]) if program.entry in rank else {}
    return sum(
        high - low
        for _, area in program.received
        for low, high in pairs_of(relative(at_entry, area))
    )


def _alone(program: PreparedProgram, table: AreaTable, parts: DemandParts) -> int:
    return _entry_bytes(program, live_sets(program.graph, parts.demand(table)))


def _resolution(table: AreaTable, node: str, site: CallSite) -> SiteResolution:
    if not table.resolved_at(node, site):
        return SiteResolution.UNRESOLVED
    if site.dynamic:
        return SiteResolution.RESOLVED
    return _named(table, site.callee)


def _named(table: AreaTable, callee: str) -> SiteResolution:
    if callee in dict(table.receives):
        return SiteResolution.STATIC
    return SiteResolution.OUTSIDE


def _place(program: PreparedProgram, node: str) -> str:
    return program.places.at(program.graph.order.index(node))


def _sites(program: PreparedProgram, table: AreaTable) -> tuple[ExplainSite, ...]:
    return tuple(
        ExplainSite(
            place=_place(program, node),
            transfer=program.places.transfer(node),
            resolution=_resolution(table, node, site),
            callees=table.callees_at(node, site),
            bytes=_alone(program, table, DemandParts(entry=((node, site, slots),))),
            reasons=_reasons(program, table, node, site),
        )
        for node, site, slots in program.parts.entry
    )


def _reasons(
    program: PreparedProgram, table: AreaTable, node: str, site: CallSite
) -> tuple[str, ...]:
    if table.resolved_at(node, site):
        return ()
    return tuple(doubt.value for doubt in dict(program.unresolved)[node].doubts)


def _sources(program: PreparedProgram, table: AreaTable) -> tuple[ExplainSource, ...]:
    parts = program.parts
    return (
        *(
            (
                ExplainSource(
                    kind=ExplainSourceKind.CALL_TARGETS,
                    bytes=_alone(program, table, DemandParts(local=parts.local)),
                ),
            )
            if parts.local
            else ()
        ),
        *(_read_backs(program, table) if parts.back else ()),
    )


def _read_backs(
    program: PreparedProgram, table: AreaTable
) -> tuple[ExplainSource, ...]:
    """What every caller reads back, and the part of it that calls no definition
    resolved read back -- charged to every member, whoever its callers are."""
    back = DemandParts(back=program.parts.back)
    return (
        ExplainSource(
            kind=ExplainSourceKind.READ_BACK, bytes=_alone(program, table, back)
        ),
        ExplainSource(
            kind=ExplainSourceKind.READ_BACK_UNRESOLVED,
            bytes=_alone(program, table.backed_by(table.dynamic_back), back),
        ),
    )


def _bytes(extents: tuple[FieldExtent, ...]) -> int:
    return sum(
        high - low
        for bounds in spans_of(extents).values()
        for low, high in pairs_of(bounds)
    )


def _kept(write: LiveWrite, exiting: frozenset[FieldExtent]) -> int:
    return _bytes(
        tuple(
            FieldExtent(
                write.target.region,
                max(one.start, write.target.start),
                min(one.end, write.target.end) - max(one.start, write.target.start),
                write.target.precision,
                write.target.field_name,
            )
            for one in exiting
            if one.region is write.target.region
            and one.start < write.target.end
            and write.target.start < one.end
        )
    )


def _widening(
    program: PreparedProgram, sets: _Sets
) -> tuple[tuple[int, str, LiveWrite, int, tuple[FieldExtent, ...]], ...]:
    graph = program.graph
    found = (
        (position, write, kept, needed_sources(write, exiting))
        for position, writes in enumerate(graph.writes)
        for exiting in (
            frozenset(
                one for after in graph.successors[position] for one in sets[after]
            ),
        )
        for write in writes
        for kept in (_kept(write, exiting),)
        if kept
    )
    return tuple(
        (wider, graph.order[position], write, kept, read)
        for position, write, kept, read in found
        for wider in (_wider(write, kept, read),)
        if wider > 0
    )


def _wider(write: LiveWrite, kept: int, read: tuple[FieldExtent, ...]) -> int:
    """Bytes a write makes live beyond those its target keeps: its sources', and,
    for a write that may leave bytes as they were, its whole target's."""
    held = 0 if strong(write) else write.target.length
    return _bytes(read) + held - kept


def _widening_row(
    program: PreparedProgram,
    found: tuple[int, str, LiveWrite, int, tuple[FieldExtent, ...]],
) -> ExplainWidening:
    _, node, write, kept, read = found
    return ExplainWidening(
        place=_place(program, node),
        target=extent_text(write.target),
        kept=kept,
        keeps_old=not strong(write),
        read=_bytes(read),
        sources=tuple(
            ranked[2]
            for ranked in sorted(
                (one.region.value, one.start, extent_text(one)) for one in read
            )
        ),
    )


def explained(program: PreparedProgram, table: AreaTable) -> ExplainRow:
    """The member's entry need; what each demand source alone needs of it; and the
    writes that make more live than their target keeps, widest first."""
    seen = table.seen_from(program.member)
    sets = live_sets(program.graph, program.parts.demand(seen))
    found = _widening(program, sets)
    order = sorted((-one[0], one[1], at) for at, one in enumerate(found))
    return ExplainRow(
        member=program.member,
        needed=_entry_bytes(program, sets),
        sources=_sources(program, seen),
        sites=_sites(program, seen),
        widening=tuple(
            _widening_row(program, found[ranked[2]]) for ranked in order[:_WIDEST]
        ),
    )
