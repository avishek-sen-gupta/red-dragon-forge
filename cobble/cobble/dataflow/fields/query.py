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
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.fields import rows
from cobble.dataflow.fields.build_corpus import (
    DEFS_FILE,
    EDGES_FILE,
    EXTENTS_FILE,
)
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.rows import Row

MAX_DEPTH = 6

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
class FieldStore:
    """The three tables a question needs, indexed for the joins it makes.

    ``nodes.jsonl`` is not read: every FIELD node it holds is an endpoint of some
    edge, so it adds no fact a query here asks for.
    """

    fields: Mapping[str, Field]
    by_name: Mapping[str, tuple[Field, ...]]
    by_program: Mapping[str, tuple[Field, ...]]
    flows: tuple[Flow, ...]
    definers: Mapping[tuple[str, str], tuple[str, ...]]

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
) -> FieldStore:
    """The three tables' rows, indexed. Rows rather than a directory, so that a
    caller holding the records in memory asks its questions of the same store a
    reader of the artefact gets -- an in-process query and a published one cannot
    then answer differently."""
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
    )


def load(out_dir: Path) -> FieldStore:
    """The artefact as one store. Missing tables load as empty, not as an error.

    A run of an older build has no defs.jsonl, and a query that answers every
    other question about it is more use than one that refuses the directory.
    """
    return store_of(
        rows.read(out_dir / EXTENTS_FILE),
        rows.read(out_dir / EDGES_FILE),
        rows.read(out_dir / DEFS_FILE),
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


def _nested_report(found: tuple[Field, ...], label: str) -> tuple[str, ...]:
    return (
        f"{label} ({len(found)}):",
        *(
            f"  level {one.level:02d}  {one.id:<40} "
            f"{', '.join(_range_text(part) for part in one.ranges)}"
            for one in found
        ),
    )


_ANSWERS: Mapping[Query, Callable[[FieldStore, Field, int], tuple[str, ...]]] = (
    MappingProxyType(
        {
            Query.EXTENTS: lambda store, field, depth: (),
            Query.WRITERS: lambda store, field, depth: _flow_report(
                store, field, Side.TARGET, "writers"
            ),
            Query.READERS: lambda store, field, depth: _flow_report(
                store, field, Side.SOURCE, "readers"
            ),
            Query.REACHES: lambda store, field, depth: _reach_report(
                store, field, Side.SOURCE, depth, "flows into"
            ),
            Query.REACHED_BY: lambda store, field, depth: _reach_report(
                store, field, Side.TARGET, depth, "flows from"
            ),
            Query.CONTAINS: lambda store, field, depth: _nested_report(
                store.contains(field), "contains"
            ),
            Query.WITHIN: lambda store, field, depth: _nested_report(
                store.containers(field), "contained by"
            ),
            Query.OVERLAPPING: lambda store, field, depth: _nested_report(
                _others(store.overlapping(field.ranges), field), "shares bytes with"
            ),
        }
    )
)
"""One arm per named question. A table rather than a match: every member of Query
is a key here, so a question added without an answer is a missing key at the one
place both are written down."""


def _answer(
    store: FieldStore, query: Query, field: Field, depth: int
) -> tuple[str, ...]:
    return _ANSWERS[query](store, field, depth)


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
    for field in found:
        sys.stdout.write("\n".join(_heading(field)) + "\n")
        sys.stdout.write(
            "\n".join(_answer(store, arguments.query, field, arguments.depth)) + "\n\n"
        )
    return 0


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Byte-interval queries over the field dataflow artefact."
    )
    parser.add_argument("query", type=Query, choices=tuple(Query))
    parser.add_argument("subject", help="a field name, or PROGRAM.FIELD to qualify it")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--depth",
        type=int,
        default=MAX_DEPTH,
        help="how many flows the transitive queries follow",
    )
    return parser.parse_args(tuple(argv) if argv else None)


def cli(argv: Sequence[str] = ()) -> int:
    arguments = _parsed(argv)
    if not arguments.out.is_dir():
        sys.stderr.write(f"fields: !! no artefact directory at {arguments.out}\n")
        return 2
    return _report(load(arguments.out), arguments)


def main() -> int:
    sys.exit(cli())
