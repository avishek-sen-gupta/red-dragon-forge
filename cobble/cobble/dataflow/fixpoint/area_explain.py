"""Why one member needs the received bytes it does: each demand source alone, and the writes that widen."""

from __future__ import annotations

from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.spans import pairs_of, spans_of
from cobble.dataflow.fixpoint.area_need import relative
from cobble.dataflow.fixpoint.area_table import AreaTable
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.demand_parts import DemandParts
from cobble.dataflow.fixpoint.live_write import LiveWrite
from cobble.dataflow.fixpoint.liveness import live_sets, needed_sources, strong
from cobble.dataflow.fixpoint.prepared_program import PreparedProgram
from cobble.dataflow.srccfg.cfg import Cfg
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


def _charged(table: AreaTable, node: str, site: CallSite) -> str:
    callees = table.callees_at(node, site)
    if not callees:
        return "dynamic, unresolved: every member's need"
    if site.dynamic:
        return f"dynamic, resolved: {', '.join(callees)}"
    return _named(table, site.callee)


def _named(table: AreaTable, callee: str) -> str:
    if callee in dict(table.receives):
        return callee
    return f"{callee}, outside the corpus: every byte"


def _place(cfg: Cfg, node: str) -> str:
    found = cfg.node(node)
    return f"{found.paragraph} line {found.span.line_start}"


def _site_label(cfg: Cfg, table: AreaTable, node: str, site: CallSite) -> str:
    return f"{_place(cfg, node)} {cfg.node(node).transfer.removeprefix('CICS_')}, {_charged(table, node, site)}"


def _sources(
    program: PreparedProgram, cfg: Cfg, table: AreaTable
) -> tuple[tuple[str, DemandParts], ...]:
    parts = program.parts
    return (
        *(
            (("call-target reads", DemandParts(local=parts.local)),)
            if parts.local
            else ()
        ),
        *(
            (
                _site_label(cfg, table, node, site),
                DemandParts(entry=((node, site, slots),)),
            )
            for node, site, slots in parts.entry
        ),
        *(
            (("callers' read-back at exits", DemandParts(back=parts.back)),)
            if parts.back
            else ()
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


def _widening_line(
    cfg: Cfg, found: tuple[int, str, LiveWrite, int, tuple[FieldExtent, ...]]
) -> str:
    _, node, write, kept, read = found
    held = "" if strong(write) else ", may keep its old bytes so all stay live"
    return (
        f"    {_place(cfg, node)}: {extent_text(write.target)} keeps {kept} bytes live{held},"
        f" reads {_bytes(read)} from {', '.join(ranked[2] for ranked in sorted((one.region.value, one.start, extent_text(one)) for one in read))}"
    )


def explained(program: PreparedProgram, cfg: Cfg, table: AreaTable) -> str:
    """The member's entry need; what each demand source alone pins of it; and the
    writes whose sources need more bytes than their target keeps live, widest first."""
    seen = table.seen_from(program.member)
    sets = live_sets(program.graph, program.parts.demand(seen))
    found = _widening(program, sets)
    order = sorted((-one[0], one[1], at) for at, one in enumerate(found))
    widest = tuple(found[ranked[2]] for ranked in order[:_WIDEST])
    return "\n".join(
        (
            f"{program.member}: {_entry_bytes(program, sets)} bytes needed on entry",
            "  by source, each alone:",
            *(
                f"  {_alone(program, seen, parts):6}  {label}"
                for label, parts in _sources(program, cfg, seen)
            ),
            "  writes that read more than their target keeps live:",
            *(_widening_line(cfg, one) for one in widest),
            "",
        )
    )
