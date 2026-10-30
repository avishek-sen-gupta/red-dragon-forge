"""What each PERFORM range can touch and which PERFORMs a walk of it can come to, computed once per program."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import reduce
from itertools import accumulate, repeat
from types import MappingProxyType
from typing import TypeVar

from cobble.dataflow.fields.extent import CellIndex, operand_extents
from cobble.dataflow.fields.spans import NO_SPANS, Spans, overlaps, spans_of, union
from cobble.dataflow.fields.state import State
from cobble.dataflow.fields.transfer import HANDLED, Statement, write_operands
from cobble.dataflow.fields.unmodelled_write import UnmodelledWrite
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent

Range = tuple[str, str]
T = TypeVar("T")
_UNFOLLOWED = frozenset({EdgeKind.PERFORM, EdgeKind.RETURN})


@dataclass(frozen=True)
class _Reach:
    """The statements a walk has reached, and those it reached on its latest step."""

    seen: frozenset[str]
    frontier: frozenset[str]


@dataclass(frozen=True)
class _Own:
    """One range's own statements' bytes and the ranges they PERFORM, callees aside."""

    spans: Spans
    calls: frozenset[Range]


@dataclass(frozen=True)
class Split:
    """A state cut in two: the entries a walk of one range can read or change, and
    the rest, which it passes through untouched."""

    inside: State
    outside: State


@dataclass(frozen=True)
class PerformRanges:
    """Per PERFORM range, keyed by its entry and the end it returns from: every byte
    a walk of it can read or write, its callees' included, and every paragraph a
    PERFORM met in that walk can name.

    A route that comes back to a PERFORM of the range's own entry ends there. That
    entry is open for the whole walk, so the PERFORM is refused, and nothing past it
    is counted: the PERFORMs a range can reach are the ones its walk can meet.
    """

    footprints: Mapping[Range, Spans] = MappingProxyType({})
    reachable: Mapping[Range, frozenset[str]] = MappingProxyType({})

    def footprint(self, entry: str, closing: str) -> Spans:
        return self.footprints.get((entry, closing), NO_SPANS)

    def reaches(self, entry: str, closing: str) -> frozenset[str]:
        return self.reachable.get((entry, closing), frozenset())


NO_RANGES = PerformRanges()


def perform_ranges(
    cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex
) -> PerformRanges:
    ranges = frozenset(
        (edge.target, cfg.node(edge.source).range_end)
        for edge in cfg.edges
        if edge.kind is EdgeKind.PERFORM
    )
    own = MappingProxyType({one: _own(cfg, statements, index, one) for one in ranges})
    return PerformRanges(
        footprints=_closed(
            own, MappingProxyType({one: own[one].spans for one in ranges}), union
        ),
        reachable=_closed(
            own,
            MappingProxyType(
                {one: frozenset(entry for entry, _ in own[one].calls) for one in ranges}
            ),
            frozenset.union,
        ),
    )


def split(state: State, footprint: Spans) -> Split:
    return Split(
        inside=_kept(state, lambda extent: overlaps(footprint, extent)),
        outside=_kept(state, lambda extent: not overlaps(footprint, extent)),
    )


def restored(inside: State, outside: State) -> State:
    """``inside`` after a walk, with the entries the walk could not touch put back."""
    return State(
        sources=MappingProxyType({**outside.sources, **inside.sources}),
        values=MappingProxyType({**outside.values, **inside.values}),
        unwritten=inside.unwritten,
    )


def _kept(state: State, keep: Callable[[FieldExtent], bool]) -> State:
    return State(
        sources=MappingProxyType(
            {extent: held for extent, held in state.sources.items() if keep(extent)}
        ),
        values=MappingProxyType(
            {extent: held for extent, held in state.values.items() if keep(extent)}
        ),
        unwritten=state.unwritten,
    )


def _own(
    cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex, one: Range
) -> _Own:
    entry, closing = one
    region = _region(cfg, entry, closing)
    names = frozenset(
        name
        for node_id in region
        for node in (cfg.node(node_id),)
        for name in (*node.reads, *node.writes)
        if name
    ) | frozenset(
        operand.name
        for node_id in region
        if node_id in statements
        for operand in _operands(statements[node_id])
    )
    return _Own(
        spans=spans_of(extent for name in names for extent in _extents(name, index)),
        calls=frozenset(
            (edge.target, cfg.node(node_id).range_end)
            for node_id in region
            for edge in cfg.successors(node_id)
            if edge.kind is EdgeKind.PERFORM and edge.target != entry
        ),
    )


def _extents(name: str, index: CellIndex) -> tuple[FieldExtent, ...]:
    """Every byte range a name can denote: as an operand, and every occurrence of its
    cells, since a subscripted name in a statement's read list carries no subscript."""
    return (
        *operand_extents(RefModOperand(name=name), index).extents,
        *(index.extent_of(cell) for cell in index.by_name.get(name.upper(), ())),
    )


def _operands(statement: Statement) -> tuple[RefModOperand, ...]:
    if isinstance(statement, UnmodelledWrite):
        return (*statement.targets, *statement.sources)
    if not isinstance(statement, HANDLED):
        return ()
    return tuple(write_operands(statement))


def _region(cfg: Cfg, entry: str, closing: str) -> frozenset[str]:
    steps = accumulate(
        repeat(None),
        lambda reach, _: _step(cfg, reach, entry, closing),
        initial=_Reach(seen=frozenset({entry}), frontier=frozenset({entry})),
    )
    return next(reach.seen for reach in steps if not reach.frontier)


def _step(cfg: Cfg, reach: _Reach, entry: str, closing: str) -> _Reach:
    found = (
        frozenset(
            target
            for node_id in reach.frontier
            for target in _onward(cfg, node_id, entry, closing)
        )
        - reach.seen
    )
    return _Reach(seen=reach.seen | found, frontier=found)


def _onward(cfg: Cfg, node_id: str, entry: str, closing: str) -> tuple[str, ...]:
    """Where a walk of the range goes from here, a PERFORM stepped over to its resume
    and a PERFORM of the range's own entry ending the route."""
    if node_id == closing:
        return ()
    edges = cfg.successors(node_id)
    plain = tuple(edge.target for edge in edges if edge.kind not in _UNFOLLOWED)
    performs = tuple(edge for edge in edges if edge.kind is EdgeKind.PERFORM)
    resume = cfg.node(node_id).resume
    if not performs or not resume or any(edge.target == entry for edge in performs):
        return plain
    return (*plain, resume)


def _closed(
    own: Mapping[Range, _Own],
    start: Mapping[Range, T],
    combine: Callable[[T, T], T],
) -> Mapping[Range, T]:
    """``start`` widened by every callee's own contribution until nothing grows."""
    rounds = accumulate(
        repeat(None),
        lambda found, _: _widened(own, found, combine),
        initial=start,
    )
    return next(found for found in rounds if _widened(own, found, combine) == found)


def _widened(
    own: Mapping[Range, _Own], found: Mapping[Range, T], combine: Callable[[T, T], T]
) -> Mapping[Range, T]:
    return MappingProxyType(
        {
            one: reduce(
                combine,
                (found[call] for call in own[one].calls if call in found),
                found[one],
            )
            for one in found
        }
    )
