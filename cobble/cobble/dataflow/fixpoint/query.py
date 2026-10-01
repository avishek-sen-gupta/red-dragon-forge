"""Questions over the field artefact, asked in bytes rather than in ids.

Names go to stdout and nowhere else: they are corpus identifiers, and the pattern
the copybook diagnostic settled on is that the machine channel carries the answer
while the log stays safe to tail.

An edge names only the smallest declared field covering the bytes it moved, so a
join on node ids answers a different question from the one asked. A group-level
write puts the group in the graph and leaves every child it filled out of it
entirely -- on the member measured, one field had three writers by byte overlap
against one by id, and twenty-one readers against none. Every predicate here
therefore starts from a field's declared ranges and intersects.

Five primitives; the named questions are compositions of them:

  ``field``                   a bare name to every program's field of that name
  ``touching``                the flows one end of which overlaps given ranges
  ``contains``/``containers`` the declared fields inside a field, or holding it
  ``overlapping``             every declared name sharing bytes with given ranges
  ``reaches``                 the transitive closure of ``touching``, over ranges

``contributed`` is what makes the collapsed edge lossless: given a flow at group
granularity and one child of that group, it recovers the source bytes that child
actually received -- the fan-out the emitter no longer writes, derived from the
two ranges and the declared layout instead of stored once per child.

Containment needs the declared level and not the ranges alone. A group with a
single child owns exactly its child's bytes, and so does a record's REDEFINES
view, so ranges alone cannot say which of such a pair holds the other.

``reaches``/``reached-by`` accept ``--across-calls`` with ``--max-hops N``
(default 3), off by default because the corpus's call graph reaches most of
itself within a few hops, so an unbounded provenance answer names half the system
and tells a reader nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from functools import reduce
from itertools import groupby
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.fixpoint.build_corpus import (
    ALIASES_FILE,
    DEFS_FILE,
    GRAPH_FILE,
)
from cobble.dataflow.fixpoint.rows import Row

MAX_DEPTH = 6

DEFAULT_HOPS = 3

FLOWS_TO = "FLOWS_TO"


class Query(Enum):
    """The named questions, spelled as the command line takes them.

    Members rather than the bare strings the dispatch used to match on, so that a
    question added here without an arm to answer it is a type error rather than a
    silent fall through to whatever the wildcard case was.
    """

    EXTENTS = "extents"
    WRITERS = "writers"
    READERS = "readers"
    REACHES = "reaches"
    REACHED_BY = "reached-by"
    CONTAINS = "contains"
    WITHIN = "within"
    OVERLAPPING = "overlapping"

    def __str__(self) -> str:
        """argparse renders choices and usage through ``str``, so this is what makes
        the help read as the words rather than as repr'd members."""
        return self.value


class Side(Enum):
    """Which end of a flow a range has to match.

    A named seam rather than a boolean, because the transitive walk reads the
    *other* end to build its next frontier and "the other end of True" is not
    something a reader should have to hold in their head.
    """

    SOURCE = auto()
    TARGET = auto()


@dataclass(frozen=True)
class Limits:
    """How far a transitive question travels: flows, and commarea crossings.

    ``hops`` of zero is not a bound of nothing -- it selects the plain walk, so
    an answer nobody asked to cross is byte-identical to what it always was.
    """

    depth: int = MAX_DEPTH
    hops: int = 0


@dataclass(frozen=True)
class Landing:
    """One field a crossing walk reached, which bytes of it, and what it cost.

    The range is carried because ``_deduped`` keeps one landing per field *and*
    overlapping bytes, so two ranges of one field are two answers: without it a
    reader sees two rows differing only in ``depth`` and reads them as a repeat.
    """

    field_id: str
    at: ByteRange
    depth: int
    hops: int
    via: str


@dataclass(frozen=True)
class Crossing:
    """What a crossing walk found."""

    landings: tuple[Landing, ...]


@dataclass(frozen=True)
class _At:
    """One place the frontier stands, carrying the cost of reaching it.

    ``via`` is the last commarea site the route here crossed, which is provenance
    for a landing.
    """

    field_id: str
    at: ByteRange
    hops: int
    via: str


@dataclass(frozen=True)
class _Cross:
    """One level of the crossing walk."""

    seen: tuple[tuple[str, ByteRange, int], ...]
    frontier: tuple[_At, ...]
    landings: tuple[tuple[int, _At], ...]
    depth: int


@dataclass(frozen=True)
class Field:
    """One declared name: how it was declared, and every range it owns."""

    id: str
    program: str
    level: int
    usage: str
    ranges: tuple[ByteRange, ...]


@dataclass(frozen=True)
class Flow:
    """One FLOWS_TO edge, with both of its extents parsed.

    The texts are kept beside the parsed ranges because the reaching-definition
    table is keyed by the source extent exactly as the artefact spells it, and
    re-rendering a range to join on it would make that key depend on this module
    agreeing with the writer character for character.
    """

    source: str
    target: str
    node: str
    source_text: str
    target_text: str
    source_range: ByteRange
    target_range: ByteRange


@dataclass(frozen=True)
class Alias:
    """One commarea's shared window, both sides parsed, or a named dead end.

    A dead end has two absent ranges and a non-empty ``reason``: a call site the
    alias phase could not resolve, rather than an edge that is merely missing.
    ``build_corpus``'s ``alias_dead_ends`` tally is what reports them. Its
    ``callee`` is present whenever the target resolved.
    """

    caller: str
    node: str
    transfer: str
    callee: str
    caller_range: ByteRange
    callee_range: ByteRange
    returns: bool
    reason: str

    @property
    def site(self) -> str:
        return f"{self.caller}:{self.node}"


@dataclass(frozen=True)
class FieldStore:
    """The four tables a question needs, indexed for the joins it makes.

    The graph file's node rows are dropped with every other non-FLOWS_TO row:
    every FIELD node is an endpoint of some edge, so they add no fact a query
    here asks for. ``aliases`` is not indexed:
    ``across`` scans every alias row per call.
    """

    fields: Mapping[str, Field]
    by_name: Mapping[str, tuple[Field, ...]]
    by_program: Mapping[str, tuple[Field, ...]]
    flows: tuple[Flow, ...]
    definers: Mapping[tuple[str, str], tuple[str, ...]]
    aliases: tuple[Alias, ...] = ()

    def field(self, wanted: str) -> tuple[Field, ...]:
        """A qualified id, or every program's field of that bare name."""
        found = self.fields.get(wanted.upper())
        if found:
            return (found,)
        return self.by_name.get(_bare(wanted), ())

    def touching(self, ranges: Sequence[ByteRange], side: Side) -> tuple[Flow, ...]:
        """Every flow whose ``side`` range overlaps any of ``ranges``."""
        return tuple(
            flow
            for flow in self.flows
            if any(_end(flow, side).overlaps(one) for one in ranges)
        )

    def overlapping(self, ranges: Sequence[ByteRange]) -> tuple[Field, ...]:
        """Every declared name owning any of ``ranges``' bytes, whole or in part.

        No level comparison and no total containment, which is what separates this
        from ``contains``/``containers``: it makes no claim about which name holds
        which, only that the bytes are shared. Both cases the other two miss are
        real. A record and its REDEFINES view own identical bytes at the same level,
        so neither direction of containment reports the other. An extent straddling
        two members is contained by neither of them.

        This is what makes an endpoint id a label rather than a claim: whichever of
        several names over one range the artefact keyed on, a reader gets the rest.
        """
        return tuple(
            sorted(
                (
                    field
                    for field in self._in_programs(ranges)
                    if any(
                        one.overlaps(part) for one in field.ranges for part in ranges
                    )
                ),
                key=_declaration_order,
            )
        )

    def _in_programs(self, ranges: Sequence[ByteRange]) -> tuple[Field, ...]:
        """Only the programs ``ranges`` name. ``overlaps`` rejects the rest anyway;
        this is so one question does not scan a whole corpus's declarations."""
        return tuple(
            field
            for program in dict.fromkeys(one.program for one in ranges if one.known)
            for field in self.by_program.get(program, ())
        )

    def contains(self, holder: Field) -> tuple[Field, ...]:
        """Every declared field whose bytes lie inside ``holder``'s.

        The level comparison is what makes this a direction rather than a
        symmetric relation: a group and its only child own identical bytes, and so
        do a record and its REDEFINES view, so ranges alone would report each of
        such a pair as inside the other.
        """
        return self._siblings(
            holder,
            lambda other: other.level > holder.level
            and _within(other.ranges, holder.ranges),
        )

    def containers(self, inner: Field) -> tuple[Field, ...]:
        """Every declared field whose bytes hold all of ``inner``'s."""
        return self._siblings(
            inner,
            lambda other: other.level < inner.level
            and _within(inner.ranges, other.ranges),
        )

    def _siblings(
        self, field: Field, holds: Callable[[Field], bool]
    ) -> tuple[Field, ...]:
        return tuple(
            sorted(
                (
                    other
                    for other in self.by_program.get(field.program, ())
                    if other.id != field.id and holds(other)
                ),
                key=_layout_order,
            )
        )

    def definers_of(self, flow: Flow) -> tuple[str, ...]:
        """The statements that could have written what this flow moved."""
        return self.definers.get((flow.node, flow.source_text), ())

    def across(
        self, ranges: Sequence[ByteRange]
    ) -> tuple[tuple[Alias, ByteRange], ...]:
        """Every live alias whose window overlaps ``ranges``, with the rebase."""
        return tuple(
            (alias, landing)
            for alias in self.aliases
            if not alias.reason  # redundant (dead row ranges are NO_RANGE), kept as intent
            for landing in _crossings(alias, ranges)
        )


def _rebased(one: ByteRange, window: ByteRange, onto: ByteRange) -> ByteRange:
    """``one``'s bytes as the other side of the alias addresses them.

    The two windows are the same storage, so an offset from the start of one is
    the same offset from the start of the other. Clipped to the window: past its
    end the two areas are not both addressable and nothing may be claimed.
    ``exact`` ignores ``window.exact`` because a clamped window would make the
    shift itself unsound. ``known=True`` relies on ``_aliased`` always writing
    both extents, ``_dead`` always setting a reason, and ``overlaps`` filtering
    ``NO_RANGE`` on the source side.
    """
    shift = onto.start - window.start
    return ByteRange(
        program=onto.program,
        region=onto.region,
        start=max(one.start, window.start) + shift,
        end=min(one.end, window.end) + shift,
        name=onto.name,
        exact=one.exact and onto.exact,
        known=True,
    )


def _one_way(
    ranges: Sequence[ByteRange], window: ByteRange, onto: ByteRange
) -> tuple[ByteRange, ...]:
    return tuple(_rebased(one, window, onto) for one in ranges if window.overlaps(one))


def _crossings(alias: Alias, ranges: Sequence[ByteRange]) -> tuple[ByteRange, ...]:
    """Inbound always; outbound only where the transfer comes back.

    ``LINK`` returns, so its caller can observe what the callee wrote and the
    alias is symmetric. ``XCTL`` never returns, so no caller observes a
    write-back and travelling that way would invent one.
    """
    inbound = _one_way(ranges, alias.caller_range, alias.callee_range)
    if not alias.returns:
        return inbound
    return (*inbound, *_one_way(ranges, alias.callee_range, alias.caller_range))


def _bare(wanted: str) -> str:
    return wanted.upper().rsplit(".", 1)[-1]


def _end(flow: Flow, side: Side) -> ByteRange:
    return flow.source_range if side is Side.SOURCE else flow.target_range


def _far_end(flow: Flow, side: Side) -> ByteRange:
    return flow.target_range if side is Side.SOURCE else flow.source_range


def _far_id(flow: Flow, side: Side) -> str:
    return flow.target if side is Side.SOURCE else flow.source


def _within(inner: Sequence[ByteRange], outer: Sequence[ByteRange]) -> bool:
    """Every one of ``inner``'s ranges sits in one of ``outer``'s.

    Every, not any: an OCCURS element owns one range per occurrence, and a group
    covering only some of them does not contain the field.
    """
    return bool(inner) and all(any(one.covers(part) for one in outer) for part in inner)


def _layout_order(field: Field) -> tuple[int, int, str]:
    first = field.ranges[0]
    return (first.start, field.level, field.id)


def _declaration_order(field: Field) -> tuple[str, int, int, str]:
    """Layout order, program first: a range query may span members, and offsets
    are region coordinates, so two programs' would otherwise interleave."""
    return (field.program, *_layout_order(field))


def contributed(flow: Flow, wanted: ByteRange) -> ByteRange:
    """The source bytes that reached ``wanted``, given a flow that covered it.

    This is the per-child fan-out the emitter stopped writing. Whenever either
    operand of a MOVE is a group the transfer is an alphanumeric byte copy, so
    byte k of the target came from byte k of the source and the tail past the
    source's end is spaces -- NO_RANGE here, which is what a padded child got.

    Only for a proper part of an EXACT target. A CLAMPED target lands somewhere
    inside its range and nothing knows where, and a whole elementary target is
    reported as taking the whole source because a numeric elementary move aligns
    on the decimal point rather than on byte zero.
    """
    target, source = flow.target_range, flow.source_range
    if not (target.exact and target.covers(wanted) and wanted.length < target.length):
        return source
    offset = wanted.start - target.start
    if offset >= source.length:
        return NO_RANGE
    return ByteRange(
        program=source.program,
        region=source.region,
        start=source.start + offset,
        end=min(source.end, source.start + offset + wanted.length),
        name=source.name,
        exact=source.exact,
        known=True,
    )


def reaches(
    store: FieldStore, start: Sequence[ByteRange], side: Side, depth: int
) -> Mapping[str, int]:
    """Field ids the walk lands on, against the depth each was first reached at.

    Over ranges, not over ids: following ids would stop at the group an edge
    names and never enter the children the group write filled. ``side`` is the end
    a frontier range has to match, so SOURCE walks forward and TARGET backward.

    Only the fields some flow named. A group this lands on reports as the group,
    and the children the group write filled are ``contains``'s answer, not a hop.

    What stops the walk is a field already visited over overlapping bytes -- both
    parts, because bytes alone would prune a sibling inside a group already
    reached, and an id alone would prune a second occurrence of a table entry.
    """
    landings = tuple(("", one) for one in start)
    return _walk(store, side, depth, _Walk(landings, landings, MappingProxyType({}), 0))


@dataclass(frozen=True)
class _Walk:
    """One level of the transitive walk: what has been landed on, and where next."""

    seen: tuple[tuple[str, ByteRange], ...]
    frontier: tuple[tuple[str, ByteRange], ...]
    found: Mapping[str, int]
    level: int


def _walk(store: FieldStore, side: Side, depth: int, walk: _Walk) -> Mapping[str, int]:
    if not walk.frontier or walk.level >= depth:
        return walk.found
    level = walk.level + 1
    landed = tuple(
        (_far_id(flow, side), _far_end(flow, side))
        for flow in store.touching(tuple(one for _, one in walk.frontier), side)
        if _unseen(flow, side, walk.seen)
    )
    return _walk(
        store,
        side,
        depth,
        _Walk(
            seen=(*walk.seen, *landed),
            frontier=landed,
            found=MappingProxyType(
                {
                    **walk.found,
                    **{at: level for at, _ in landed if at not in walk.found},
                }
            ),
            level=level,
        ),
    )


def _unseen(flow: Flow, side: Side, seen: Sequence[tuple[str, ByteRange]]) -> bool:
    landing, at = _far_end(flow, side), _far_id(flow, side)
    return landing.known and not any(
        at == other and landing.overlaps(one) for other, one in seen
    )


def crossing(
    store: FieldStore,
    start: Sequence[ByteRange],
    side: Side,
    depth: int,
    hops: int,
) -> Crossing:
    """``reaches``, but a commarea window is a step the walk may take.

    Separate from ``reaches`` rather than a flag on it, for two reasons: the
    default answer stays byte-identical because it is still the same function,
    and what a crossing answer has to carry -- which site it went through, and
    how many -- is a different shape from a depth per field.

    The seed names itself so a commarea round trip is not a new landing. ``hops``
    is the minimum among routes found within the depth budget, not the global
    minimum.
    """
    at = tuple(_At(field_id=_qualified(one), at=one, hops=0, via="") for one in start)
    return _crossed(
        store,
        side,
        depth,
        hops,
        _Cross(
            seen=tuple((one.field_id, one.at, 0) for one in at),
            frontier=at,
            landings=(),
            depth=0,
        ),
    )


def _crossed(
    store: FieldStore, side: Side, depth: int, hops: int, walk: _Cross
) -> Crossing:
    if not walk.frontier or walk.depth >= depth:
        return Crossing(landings=_deduped(walk.landings))
    return _crossed(store, side, depth, hops, _stepped(store, side, hops, walk))


def _stepped(store: FieldStore, side: Side, hops: int, walk: _Cross) -> _Cross:
    """One level: every flow the frontier touches, then every alias it can cross."""
    reached = (*_flow_step(store, side, walk), *_alias_step(store, hops, walk))
    fresh = _canonical(tuple(one for one in reached if _fresh(one, walk.seen)))
    return _Cross(
        seen=(*walk.seen, *((one.field_id, one.at, one.hops) for one in fresh)),
        frontier=fresh,
        landings=(*walk.landings, *((walk.depth + 1, one) for one in fresh)),
        depth=walk.depth + 1,
    )


def _canonical(fresh: Sequence[_At]) -> tuple[_At, ...]:
    """One entry per field and bytes, at the cheapest cost this level admitted.

    ``_fresh`` compares against the levels before this one, so two arrivals in the
    same level never see each other and a level can hold the same bytes at two
    costs. ``_from`` and ``_deduped`` both take the minimum, so the dearer twin
    changes no reported cost -- what it does is ride the frontier into the next
    level and cross again, multiplying arrivals the answer will discard anyway.
    """
    return tuple(
        min((one for one in fresh if (one.field_id, one.at) == place), key=_cost)
        for place in dict.fromkeys((one.field_id, one.at) for one in fresh)
    )


def _flow_step(store: FieldStore, side: Side, walk: _Cross) -> tuple[_At, ...]:
    ranges = tuple(one.at for one in walk.frontier)
    return tuple(
        _stepped_from(_from(walk.frontier, _end(flow, side)), flow, side)
        for flow in store.touching(ranges, side)
    )


def _stepped_from(came: _At, flow: Flow, side: Side) -> _At:
    """A flow costs no hop, so the cost of standing here carries forward."""
    return _At(
        field_id=_far_id(flow, side),
        at=_far_end(flow, side),
        hops=came.hops,
        via=came.via,
    )


def _cost(one: _At) -> int:
    return one.hops


def _from(frontier: Sequence[_At], near: ByteRange) -> _At:
    """The cheapest frontier entry a flow's near end matched, so its cost is known.

    Cheapest and not merely the first met: a flow costs no hop, so pricing it off a
    dearer entry over the same bytes reports a route costlier than the one that
    actually reached them, and every landing downstream inherits the inflation.

    The entry is guaranteed to exist because ``touching`` was asked with these
    very ranges."""
    return min((one for one in frontier if one.at.overlaps(near)), key=_cost)


def _crossings_from(store: FieldStore, one: _At) -> tuple[_At, ...]:
    return tuple(
        _At(
            field_id=_qualified(landing),
            at=landing,
            hops=one.hops + 1,
            via=alias.site,
        )
        for alias, landing in store.across((one.at,))
    )


def _alias_step(store: FieldStore, hops: int, walk: _Cross) -> tuple[_At, ...]:
    """The crossings this level takes, the hop cap refusing the rest."""
    return tuple(
        landed
        for one in walk.frontier
        if one.hops < hops
        for landed in _crossings_from(store, one)
    )


def _qualified(one: ByteRange) -> str:
    return f"{one.program}.{one.name}".upper()


def _fresh(one: _At, seen: Sequence[tuple[str, ByteRange, int]]) -> bool:
    """Not stood on over overlapping bytes at or below this entry's hops.

    The relaxed filter re-admits a cheaper arrival, which does not risk
    termination: ``_crossed`` is bounded by ``walk.depth >= depth`` regardless
    of what ``seen`` admits.
    """
    return one.at.known and not any(
        one.field_id == other and one.at.overlaps(part) and seen_hops <= one.hops
        for other, part, seen_hops in seen
    )


def _deduped(at_landings: tuple[tuple[int, _At], ...]) -> tuple[Landing, ...]:
    """Best landing per field and overlapping bytes: minimum hops, then depth."""
    by_field = groupby(
        sorted(at_landings, key=lambda pair: pair[1].field_id),
        key=lambda pair: pair[1].field_id,
    )
    kept = tuple(
        (depth, at)
        for _, group in by_field
        for depth, at in _kept_from_group(tuple(group))
    )
    return tuple(
        Landing(field_id=at.field_id, at=at.at, depth=depth, hops=at.hops, via=at.via)
        for depth, at in sorted(
            kept, key=lambda pair: (pair[1].hops, pair[0], pair[1].field_id)
        )
    )


def _kept_from_group(group: tuple[tuple[int, _At], ...]) -> tuple[tuple[int, _At], ...]:
    """Within one field_id group, keep entries not superseded by overlapping bytes."""
    sorted_group = tuple(sorted(group, key=lambda pair: (pair[1].hops, pair[0])))
    return reduce(_add_if_not_superseded, sorted_group, ())


def _add_if_not_superseded(
    kept: tuple[tuple[int, _At], ...], candidate: tuple[int, _At]
) -> tuple[tuple[int, _At], ...]:
    _, at = candidate
    superseded = any(prior_at.at.overlaps(at.at) for _prior_depth, prior_at in kept)
    return kept if superseded else (*kept, candidate)


def _program_of(field_id: str) -> str:
    return field_id.split(".", 1)[0]


def _field(row: Row) -> Field:
    field_id = rows.text(row, "id")
    program = _program_of(field_id)
    return Field(
        id=field_id,
        program=program,
        level=rows.number(row, "level"),
        usage=rows.text(row, "usage"),
        ranges=tuple(byte_range(one, program) for one in rows.strings(row, "extents")),
    )


def _flow(row: Row) -> Flow:
    attrs = rows.nested(row, "attrs")
    source, target = rows.text(row, "source"), rows.text(row, "target")
    source_text = rows.text(attrs, "source_extent")
    target_text = rows.text(attrs, "target_extent")
    return Flow(
        source=source,
        target=target,
        node=rows.text(attrs, "node"),
        source_text=source_text,
        target_text=target_text,
        source_range=byte_range(source_text, _program_of(source)),
        target_range=byte_range(target_text, _program_of(target)),
    )


def _alias(row: Row) -> Alias:
    caller, callee = rows.text(row, "caller"), rows.text(row, "callee")
    return Alias(
        caller=caller,
        node=rows.text(row, "node"),
        transfer=rows.text(row, "transfer"),
        callee=callee,
        caller_range=byte_range(rows.text(row, "caller_extent"), caller),
        callee_range=byte_range(rows.text(row, "callee_extent"), callee),
        returns=rows.flag(row, "returns"),
        reason=rows.text(row, "reason"),
    )


def _grouped(
    fields: tuple[Field, ...], key: Callable[[Field], str]
) -> Mapping[str, tuple[Field, ...]]:
    keyed = tuple((key(field), field) for field in fields)
    return MappingProxyType(
        {
            value: tuple(field for other, field in keyed if other == value)
            for value in dict.fromkeys(value for value, _ in keyed)
        }
    )


def _name_of(field: Field) -> str:
    return _bare(field.id)


def _program_key(field: Field) -> str:
    return field.program


def store_of(
    declared: Sequence[Row],
    edges: Sequence[Row],
    defs: Sequence[Row],
    aliases: Iterable[Row] = (),
) -> FieldStore:
    """The four tables' rows, indexed where the joins need it. Rows rather than a
    directory, so that a caller holding the records in memory asks its questions
    of the same store a reader of the artefact gets -- an in-process query and a
    published one cannot then answer differently."""
    fields = tuple(_field(row) for row in declared)
    return FieldStore(
        fields=MappingProxyType({field.id: field for field in fields}),
        by_name=_grouped(fields, _name_of),
        by_program=_grouped(fields, _program_key),
        flows=tuple(_flow(row) for row in edges if rows.text(row, "kind") == FLOWS_TO),
        definers=MappingProxyType(
            {
                (rows.text(row, "node"), rows.text(row, "extent")): rows.strings(
                    row, "definers"
                )
                for row in defs
            }
        ),
        aliases=tuple(_alias(row) for row in aliases),
    )


def load(out_dir: Path, extents: Path) -> FieldStore:
    """The artefact, joined with the extents table the fixpoint read, as one store.
    Missing tables load as empty, not as an error.

    A run of an older build has no defs.jsonl, and a query that answers every
    other question about it is more use than one that refuses the directory.
    """
    return store_of(
        rows.read(extents),
        rows.read(out_dir / GRAPH_FILE),
        rows.read(out_dir / DEFS_FILE),
        rows.read(out_dir / ALIASES_FILE),
    )


def _range_text(one: ByteRange) -> str:
    if not one.known:
        return "(not storage)"
    mark = "" if one.exact else " may"
    return f"{one.name}@{one.region}[{one.start}:{one.end}]{mark}"


def _flow_line(store: FieldStore, flow: Flow, side: Side) -> str:
    """One flow as a person reads it: which node, which field, which bytes."""
    definers = ", ".join(store.definers_of(flow)) or "-"
    return (
        f"  {flow.node:<14} {_far_id(flow, side):<40} "
        f"{_range_text(flow.source_range)} -> {_range_text(flow.target_range)}"
        f"  [defined at {definers}]"
    )


def _shares(flow: Flow, wanted: Field) -> str:
    """Which of the source's bytes each of this field's ranges received.

    Only on the writer report: on a read the field is the source, and where its
    bytes ended up is the target's own extent, already on the line above.
    """
    got = tuple(
        _range_text(contributed(flow, one))
        for one in wanted.ranges
        if flow.target_range.covers(one) and one.length < flow.target_range.length
    )
    return f"    of which {wanted.id} took {', '.join(got)}" if got else ""


def _heading(field: Field) -> tuple[str, ...]:
    declared = ", ".join(_range_text(one) for one in field.ranges)
    usage = field.usage if field.usage else "(group)"
    return (
        f"{field.id}  level {field.level:02d}  usage {usage}",
        f"  declared at {declared}",
    )


def _flow_report(
    store: FieldStore, field: Field, side: Side, label: str
) -> tuple[str, ...]:
    flows = store.touching(field.ranges, side)
    lines = tuple(
        line
        for flow in flows
        for line in (_flow_line(store, flow, side), _split(flow, field, side))
        if line
    )
    return (f"{label} ({len(flows)}):", *lines)


def _split(flow: Flow, field: Field, side: Side) -> str:
    return _shares(flow, field) if side is Side.TARGET else ""


def _reach_report(
    store: FieldStore, field: Field, limits: Limits, label: str, side: Side
) -> tuple[str, ...]:
    if limits.hops:
        return _crossing_report(store, field, side, limits, label)
    return _plain_reach_report(store, field, side, limits.depth, label)


def _plain_reach_report(
    store: FieldStore, field: Field, side: Side, depth: int, label: str
) -> tuple[str, ...]:
    found = reaches(store, field.ranges, side, depth)
    return (
        f"{label} (depth {depth}, {len(found)} fields):",
        *(
            f"  {at_depth}  {field_id}"
            for field_id, at_depth in sorted(found.items(), key=lambda pair: pair[::-1])
        ),
    )


def _crossing_report(
    store: FieldStore, field: Field, side: Side, limits: Limits, label: str
) -> tuple[str, ...]:
    found = crossing(store, field.ranges, side, limits.depth, limits.hops)
    return (
        (
            f"{label} across calls (depth {limits.depth}, max {limits.hops} hops, "
            f"{len(found.landings)} landings):"
        ),
        *(_landing_line(one) for one in found.landings),
    )


def _landing_line(one: Landing) -> str:
    via = f"  via {one.via}" if one.via else ""
    return f"  hop {one.hops}  depth {one.depth}  {one.field_id}  {one.at}{via}"


def _nested_report(found: tuple[Field, ...], label: str) -> tuple[str, ...]:
    return (
        f"{label} ({len(found)}):",
        *(
            f"  level {one.level:02d}  {one.id:<40} "
            f"{', '.join(_range_text(part) for part in one.ranges)}"
            for one in found
        ),
    )


_ANSWERS: Mapping[Query, Callable[[FieldStore, Field, Limits], tuple[str, ...]]] = (
    MappingProxyType(
        {
            Query.EXTENTS: lambda store, field, limits: (),
            Query.WRITERS: lambda store, field, limits: _flow_report(
                store, field, Side.TARGET, "writers"
            ),
            Query.READERS: lambda store, field, limits: _flow_report(
                store, field, Side.SOURCE, "readers"
            ),
            Query.REACHES: lambda store, field, limits: _reach_report(
                store, field, limits, "flows into", Side.SOURCE
            ),
            Query.REACHED_BY: lambda store, field, limits: _reach_report(
                store, field, limits, "flows from", Side.TARGET
            ),
            Query.CONTAINS: lambda store, field, limits: _nested_report(
                store.contains(field), "contains"
            ),
            Query.WITHIN: lambda store, field, limits: _nested_report(
                store.containers(field), "contained by"
            ),
            Query.OVERLAPPING: lambda store, field, limits: _nested_report(
                _others(store.overlapping(field.ranges), field), "shares bytes with"
            ),
        }
    )
)
"""One arm per named question. A table rather than a match: every member of Query
is a key here, so a question added without an answer is a missing key at the one
place both are written down."""


def _answer(
    store: FieldStore, query: Query, field: Field, limits: Limits
) -> tuple[str, ...]:
    return _ANSWERS[query](store, field, limits)


def _others(found: tuple[Field, ...], field: Field) -> tuple[Field, ...]:
    """``overlapping`` reports every owner of the bytes, this field included, since
    a range query has no subject to exclude. A report does, and the heading above
    already named it."""
    return tuple(one for one in found if one.id != field.id)


def _report(store: FieldStore, arguments: argparse.Namespace) -> int:
    found = store.field(arguments.subject)
    if not found:
        sys.stdout.write(f"no declared field named {arguments.subject}\n")
        return 1
    limits = _limits_of(arguments)
    for field in found:
        sys.stdout.write("\n".join(_heading(field)) + "\n")
        sys.stdout.write(
            "\n".join(_answer(store, arguments.query, field, limits)) + "\n\n"
        )
    return 0


def _hop_budget(given: str) -> int:
    """Zero hops is what the default already is, so asking for it while also
    asking to cross calls is a contradiction rather than a setting."""
    count = int(given)
    if count < 1:
        raise argparse.ArgumentTypeError(f"needs at least one hop, got {count}")
    return count


def _limits_of(arguments: argparse.Namespace) -> Limits:
    return Limits(
        depth=arguments.depth,
        hops=arguments.max_hops if arguments.across_calls else 0,
    )


_CROSSABLE = (Query.REACHES, Query.REACHED_BY)
"""The questions ``--across-calls`` means something for: the transitive two."""


def _crossable(
    parser: argparse.ArgumentParser, arguments: argparse.Namespace
) -> argparse.Namespace:
    """Refused rather than ignored where the question cannot cross a call.

    A callee's write into the shared window genuinely is a writer of the caller's
    bytes, so ``writers`` and ``readers`` are meaningful questions to ask across a
    call and this analysis does not answer them. Accepting the flag and answering
    without it would be indistinguishable from a corpus where no call shares any.
    """
    if arguments.across_calls and arguments.query not in _CROSSABLE:
        parser.error(
            f"--across-calls applies to {' and '.join(map(str, _CROSSABLE))}, "
            f"not to {arguments.query}"
        )
    return arguments


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = _parser()
    return _crossable(parser, parser.parse_args(tuple(argv) if argv else None))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Byte-interval queries over the field dataflow artefact."
    )
    parser.add_argument("query", type=Query, choices=tuple(Query))
    parser.add_argument("subject", help="a field name, or PROGRAM.FIELD to qualify it")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--extents",
        required=True,
        type=Path,
        help="extents.jsonl from cobble-extents: the layout the fixpoint read",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=MAX_DEPTH,
        help="how many flows the transitive queries follow",
    )
    parser.add_argument(
        "--across-calls",
        action="store_true",
        help="let reaches/reached-by cross a commarea window into the callee",
    )
    parser.add_argument(
        "--max-hops",
        type=_hop_budget,
        default=DEFAULT_HOPS,
        metavar="N",
        help="commarea crossings allowed per path, with --across-calls",
    )
    return parser


def cli(argv: Sequence[str] = ()) -> int:
    arguments = _parsed(argv)
    if not arguments.out.is_dir():
        sys.stderr.write(f"fields: !! no artefact directory at {arguments.out}\n")
        return 2
    if not arguments.extents.is_file():
        sys.stderr.write(f"fields: !! no extents table at {arguments.extents}\n")
        return 2
    return _report(load(arguments.out, arguments.extents), arguments)


def main() -> int:
    sys.exit(cli())
