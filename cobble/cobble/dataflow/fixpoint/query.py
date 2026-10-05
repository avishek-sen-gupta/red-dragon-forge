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
import logging
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property, reduce
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from types import MappingProxyType

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.fixpoint.build_corpus import (
    ALIASES_FILE,
    DEFS_FILE,
    GRAPH_FILE,
)
from cobble.dataflow.fixpoint.rows import Row

logger = logging.getLogger(__name__)

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
    definers: Mapping[tuple[str, str, str], tuple[str, ...]]
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

    def following(self, flow: Flow, side: Side) -> tuple[Flow, ...]:
        """The flows a walk may take next from ``flow``, in statement order.

        Forward (``SOURCE``), the reads its write reaches: a flow whose source bytes
        overlap this one's target, at a statement that lists this one's as a
        definer. Backward (``TARGET``), the writes its read can see: a flow whose
        target bytes overlap this one's source, at one of this one's definers. A
        flow at a statement its write cannot reach -- one that ran first, or after
        an overwrite -- is never a next step, which is what a walk over fields
        alone could not tell.
        """
        if side is Side.SOURCE:
            return tuple(
                later
                for later in self._reads_after.get(_flow_at(flow), ())
                if later.source_range.overlaps(flow.target_range)
            )
        return tuple(
            earlier
            for definer in self.definers_of(flow)
            for earlier in self._at_statement.get(
                (_program_of(flow.target), definer), ()
            )
            if earlier.target_range.overlaps(flow.source_range)
        )

    @cached_property
    def _at_statement(self) -> Mapping[tuple[str, str], tuple[Flow, ...]]:
        logger.info("indexing %d flows by statement", len(self.flows))
        return _flows_by((_flow_at(flow), flow) for flow in self.flows)

    @cached_property
    def _reads_after(self) -> Mapping[tuple[str, str], tuple[Flow, ...]]:
        """Each statement, against the flows whose reads its writes reach."""
        logger.info(
            "indexing %d flows by the statements that define them", len(self.flows)
        )
        return _flows_by(
            ((_program_of(flow.target), definer), flow)
            for flow in self.flows
            for definer in self.definers_of(flow)
        )

    def definers_of(self, flow: Flow) -> tuple[str, ...]:
        """The statements that could have written what this flow moved."""
        return self.definers.get(
            (_program_of(flow.source), flow.node, flow.source_text), ()
        )

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

    The walk goes from flow to flow, and only in statement order: forward from a
    write to the reads it reaches, backward from a read to the writes it can see,
    as ``FieldStore.following`` says. A value copied into B after B was copied on
    to C does not reach C. ``side`` is the end a starting flow's range has to
    match, so SOURCE walks forward and TARGET backward.

    Over ranges, not over ids: a group write's flow overlaps every child it
    filled, so the walk enters them. A group it lands on reports as the group, and
    the children are ``contains``'s answer, not a hop. ``depth`` bounds the walk;
    each flow is taken once, so a loop costs one pass rather than one per level.
    """
    first = store.touching(start, side)
    return _walk(
        store,
        side,
        depth,
        _Walk(
            seen=frozenset(first),
            frontier=first,
            found=_landed({}, first, side, 1),
            level=1,
        ),
    )


@dataclass(frozen=True)
class _Walk:
    """One level of the transitive walk: the flows taken, and the ones to go on from."""

    seen: frozenset[Flow]
    frontier: tuple[Flow, ...]
    found: Mapping[str, int]
    level: int


def _walk(store: FieldStore, side: Side, depth: int, walk: _Walk) -> Mapping[str, int]:
    logger.info(
        "depth %d: %d flows to go on from, %d fields found",
        walk.level,
        len(walk.frontier),
        len(walk.found),
    )
    if not walk.frontier or walk.level >= depth:
        return MappingProxyType(dict(walk.found))
    level = walk.level + 1
    taken = tuple(
        dict.fromkeys(
            after
            for flow in walk.frontier
            for after in store.following(flow, side)
            if after not in walk.seen
        )
    )
    return _walk(
        store,
        side,
        depth,
        _Walk(
            seen=walk.seen | frozenset(taken),
            frontier=taken,
            found=_landed(walk.found, taken, side, level),
            level=level,
        ),
    )


def _landed(
    found: Mapping[str, int], flows: Sequence[Flow], side: Side, level: int
) -> Mapping[str, int]:
    """The far ends ``flows`` land on that no earlier level did. A far end that is
    not storage -- a literal, a file -- ends its chain without being a landing."""
    return {
        **{
            _far_id(flow, side): level
            for flow in reversed(flows)
            if _far_end(flow, side).known and _far_id(flow, side) not in found
        },
        **found,
    }


def _flow_at(flow: Flow) -> tuple[str, str]:
    return (_program_of(flow.target), flow.node)


def _flows_by(
    pairs: Iterable[tuple[tuple[str, str], Flow]],
) -> Mapping[tuple[str, str], tuple[Flow, ...]]:
    ordered = sorted(pairs, key=itemgetter(0))
    return MappingProxyType(
        {
            statement: tuple(flow for _, flow in group)
            for statement, group in groupby(ordered, key=itemgetter(0))
        }
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
                (
                    rows.text(row, "program"),
                    rows.text(row, "node"),
                    rows.text(row, "extent"),
                ): rows.strings(row, "definers")
                for row in defs
            }
        ),
        aliases=tuple(_alias(row) for row in aliases),
    )


def load(out_dir: Path, extents: Path, links: Path = Path()) -> FieldStore:
    """The artefact, joined with the extents table the fixpoint read, as one store.
    Missing tables load as empty, not as an error.

    A run of an older build has no defs.jsonl, and a query that answers every
    other question about it is more use than one that refuses the directory.
    """
    return _ready(_table(extents), out_dir, links)


def load_for(
    out_dir: Path, extents: Path, subject: str, links: Path = Path()
) -> FieldStore:
    """``load``, keeping only the declarations of the programs ``subject`` is
    declared in.

    The extents table is one row per declared field, grouped by program, and it is
    large: a record's row carries all of its cells. A question about one field needs
    only its own programs' declarations -- the flows come from the graph, and every
    other answer stays inside the subject's program. So the table is streamed one
    program's rows at a time and a program is kept only if it declares the subject:
    a qualified ``PROGRAM.FIELD`` keeps that program, a bare name every program
    declaring it. Memory is the kept programs and the one being read, not the table.
    """
    return _ready(_declaring(extents, subject), out_dir, links)


def _ready(declared: Sequence[Row], out_dir: Path, links: Path = Path()) -> FieldStore:
    store = store_of(
        declared,
        _table(out_dir / GRAPH_FILE),
        _table(out_dir / DEFS_FILE),
        _table(links if links != Path() else out_dir / ALIASES_FILE),
    )
    logger.info(
        "ready: %d fields, %d flows, %d definer rows",
        len(store.fields),
        len(store.flows),
        len(store.definers),
    )
    return store


PROGRESS_EVERY = 100


def _declaring(path: Path, subject: str) -> tuple[Row, ...]:
    if not path.is_file():
        logger.info("%s: not there, read as empty", path.name)
        return ()
    logger.info(
        "scanning %s (%.1f MB) for the programs declaring the subject",
        path.name,
        path.stat().st_size / 1e6,
    )
    kept = tuple(
        block
        for at, block in enumerate(_program_blocks(path), start=1)
        if _scanned(at) and _declares(block, subject) and _kept(block)
    )
    found = tuple(row for block in kept for row in block)
    logger.info("%s: kept %d programs, %d rows", path.name, len(kept), len(found))
    return found


def _program_blocks(path: Path) -> Iterator[tuple[Row, ...]]:
    """The table's rows a program at a time. A program's rows are contiguous, and a
    row's program is its id's qualifier, as everywhere else here."""
    return (tuple(block) for _, block in groupby(rows.stream(path), _row_program))


def _row_program(row: Row) -> str:
    return _program_of(rows.text(row, "id"))


def _scanned(at: int) -> bool:
    """Says how far a long scan has got, every ``PROGRESS_EVERY`` programs; always
    true, so it can sit in the scan's filter."""
    if not at % PROGRESS_EVERY:
        logger.info("scanned %d programs", at)
    return True


def _kept(block: Sequence[Row]) -> bool:
    """Says which program the scan kept, as it keeps it; always true."""
    logger.info("kept %s: %d rows", _program_of(rows.text(block[0], "id")), len(block))
    return True


def _declares(block: Sequence[Row], subject: str) -> bool:
    """A qualified subject names one field id; a bare one, any field of that name."""
    wanted = subject.upper()
    if "." in wanted:
        return any(rows.text(row, "id").upper() == wanted for row in block)
    return any(_bare(rows.text(row, "id")) == wanted for row in block)


def _table(path: Path) -> tuple[Row, ...]:
    """One table, read whole, with its size said first: a large artefact takes a
    while to read, and a command that says nothing looks hung."""
    if not path.is_file():
        logger.info("%s: not there, read as empty", path.name)
        return ()
    logger.info("reading %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    found = rows.read(path)
    logger.info("%s: %d rows", path.name, len(found))
    return found


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
    logger.info("answering %s", arguments.query)
    for at, field in enumerate(found, start=1):
        logger.info("field %d of %d", at, len(found))
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
    parser.add_argument(
        "--fixpoint-dir",
        required=True,
        type=Path,
        help="the directory cobble-dataflow-fixpoint wrote (its --out-dir)",
    )
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
    parser.add_argument(
        "--links",
        type=Path,
        default=Path(),
        help="links.jsonl from cobble-dataflow-combine, read in place of aliases.jsonl",
    )
    return parser


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parsed(argv)
    if not arguments.fixpoint_dir.is_dir():
        sys.stderr.write(
            f"fields: !! no fixpoint directory at {arguments.fixpoint_dir}\n"
        )
        return 2
    if not arguments.extents.is_file():
        sys.stderr.write(f"fields: !! no extents table at {arguments.extents}\n")
        return 2
    return _report(
        load_for(
            arguments.fixpoint_dir,
            arguments.extents,
            arguments.subject,
            arguments.links,
        ),
        arguments,
    )


def main() -> int:
    sys.exit(cli())
