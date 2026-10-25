"""The tables beside the graph, and the one sink that streams any of them.

None of them is a graph fact, so none of them is in the graph.

``extents.jsonl`` says where every *declared* field is, whether a value ever
moved through it or not, plus the level and usage it was declared with. Level is
there because ranges alone cannot resolve containment: a group with a single
child owns exactly its child's bytes, and so does a record's REDEFINES view, and
only the declared level says which of the pair holds the other. Usage is there
because a partial overlap of a COMP or COMP-3 field is not a partial read of its
value -- a consumer that slices one is reading half a packed number. With both,
the whole record tree and the byte correspondence of a group move are derivable
from this table plus the two ranges an edge carries, which is why no edge
carries either.

Beside those four it carries one column per declared property of a cell, parallel
to ``extents``, plus its record's origin, size and place in declaration order.
That is the whole of ``layout``'s answer, so a stage that needs the records --
the fixpoint, which seeds its entry state from the VALUE image -- reads them here
instead of laying the DATA DIVISION out a second time.

``defs.jsonl`` says which statements could have last written one byte range by
the time one CFG node runs. Its own table because the relation is keyed by
(node, range) and not by the flow: one source range at one node had a hundred
reaching definers on the member measured, and 862 of its 5261 (node, source,
target) triples had more than one. Pinned onto the edge, each of those became one
edge per definer, all stating the same flow. Here it is one row, and an edge that
wants the definers joins on the pair it already names.

``aliases.jsonl`` says which bytes a call site shares between two programs. Its
own table because a row belongs to neither program's flow graph -- it is the
relation between them.

``targets.jsonl`` says which programs a dynamic CALL/XCTL/LINK site can reach.
Its own table for the same reason as ``aliases.jsonl``: a call site's possible
callees are not a fact about either program's field graph.

Same temp-and-rename discipline as GraphWriter, so a crashed run leaves no
truncated file, and the same keep-first dedupe: two members declaring one
program_id is normal on a real corpus, and the first one analysed is the one
whose layout the ids in the graph were named from.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.fields.values import EMPTY as VALUES_EMPTY
from cobble.dataflow.fields.values import ValueSet
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.targets import ResolvedTarget
from cobble.dataflow.jumps.rows import fact_dict
from cobble.dataflow.layout import Cell
from cobble.sink_state import FirstSighting


@dataclass(frozen=True)
class DeclaredRecord:
    """Where one record sits among the program's records.

    A cell names its record but says nothing about the record itself, and the
    record's own three facts are what a reader rebuilding the layout is missing:
    which section allocated it, how many bytes it owns -- the widest view of it,
    which is not the last cell's end -- and its place in declaration order, which
    is what lays the section's records end to end at the right bases.
    """

    origin: str
    size: int
    position: int


@dataclass(frozen=True)
class DeclaredCell:
    """One occurrence of one field, with the facts of the record holding it."""

    cell: Cell
    record: DeclaredRecord


@dataclass(frozen=True)
class FieldExtents:
    """One declared name, how it was declared, and every byte range it owns.

    A list of ranges because a name owns more than one whenever OCCURS gives it
    an occurrence per subscript, or two records declare it independently. Not the
    span from the first range to the last: between two occurrences of an element
    lie its siblings' bytes, and a single spanning range would report this field
    as covered by a write that only ever touched them.

    ``cells`` is those same occurrences in the same order, each with everything
    its ``Cell`` was declared with -- which is what makes the table a layout a
    reader can rebuild rather than only a geometry it can intersect. ``level`` and
    ``usage`` stay where they are, both the first cell's, because that is what the
    table has always published; a name two records declare at different levels
    carries both in ``cells`` and the first of them at the top.
    """

    id: str
    level: int
    usage: str
    extents: tuple[str, ...]
    program: str = ""
    cells: tuple[DeclaredCell, ...] = ()


@dataclass(frozen=True)
class ReachingDefs:
    """Which statements could have written ``extent`` by the time ``node`` runs.

    Plural, and irreducibly so: two arms of a branch both reach the node, and
    nothing short of a path-sensitive walk says which one ran.
    """

    program: str
    node: str
    extent: str
    definers: tuple[str, ...]
    held: ValueSet = VALUES_EMPTY


@dataclass(frozen=True)
class CommareaAlias:
    """One call site's shared commarea window, or a named reason there is none.

    ``caller`` is always present; ``node`` and ``transfer`` are present on every
    per-site row, so a site that could not be aliased is a row a consumer can read
    rather than an absence it has to interpret. Both are blank on the one row that
    reports the alias pass failing before it could enumerate a member's sites, where
    there is no site to name, which is the one row whose blank ``callee`` says
    nothing about the target either. On every other row ``callee`` is blank exactly
    when the target is a field rather than a literal and nothing short of running the
    program resolves it. ``returns`` is false for XCTL, which never comes back.
    """

    caller: str
    node: str
    transfer: str
    callee: str = ""
    caller_extent: str = ""
    callee_extent: str = ""
    returns: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ProgramSink:
    """Bytes leaving ``program`` at ``node`` by ``sink``, and the statements that last wrote them."""

    program: str
    node: str
    sink: str
    source_extent: str
    definers: tuple[str, ...]


_Row = tuple[str, str]


_Column = str | int | bool | tuple[str, ...] | tuple[int, ...]

_CELL_COLUMNS: Mapping[str, Callable[[DeclaredCell], _Column]] = MappingProxyType(
    {
        "names": lambda one: one.cell.name,
        "records": lambda one: one.cell.record,
        "paths": lambda one: one.cell.path,
        "starts": lambda one: one.cell.start,
        "lengths": lambda one: one.cell.length,
        "levels": lambda one: one.cell.level,
        "pics": lambda one: one.cell.pic,
        "usages": lambda one: one.cell.usage,
        "redefines": lambda one: one.cell.redefines,
        "occurs": lambda one: one.cell.occurs,
        "values": lambda one: one.cell.value,
        "figurative": lambda one: one.cell.value_is_figurative,
        "indexes": lambda one: one.cell.index,
        "decls": lambda one: one.cell.decl,
        "ordinals": lambda one: one.cell.ordinal,
        "parents": lambda one: one.cell.parent,
        "origins": lambda one: one.record.origin,
        "record_sizes": lambda one: one.record.size,
        "record_positions": lambda one: one.record.position,
    }
)


def _cell_columns(cells: Sequence[DeclaredCell]) -> Mapping[str, tuple[_Column, ...]]:
    """One array per declared property, each parallel to ``extents``.

    Columns rather than one object per cell: a member's records hold 569226 cells
    between them, and an object apiece would spell all nineteen field names once
    per cell. Those names are the cost worth removing; a reader indexes the arrays
    by position, the same position the extent at that index was written from.
    """
    return {
        name: tuple(column(one) for one in cells)
        for name, column in _CELL_COLUMNS.items()
    }


def extent_row(field: FieldExtents) -> _Row:
    """One declared field's row, under the id the writer dedupes on.

    The first four fields are the row as it has always been, in the order it has
    always had: a consumer reading ``id``, ``level``, ``usage`` and ``extents``
    reads the same values from a row carrying the layout columns as from one
    written before they existed.
    """
    return (
        field.id,
        json.dumps(
            {
                "id": field.id,
                "level": field.level,
                "usage": field.usage,
                "extents": list(field.extents),
                "program": field.program,
                **_cell_columns(field.cells),
            }
        ),
    )


def defs_identity(program: str, node: str, extent: str) -> str:
    return f"{program}\x00{node}\x00{extent}"


def sink_identity(sink: ProgramSink) -> str:
    return "\x00".join((sink.program, sink.node, sink.sink, sink.source_extent))


def alias_identity(caller: str, node: str, caller_extent: str) -> str:
    return f"{caller}\x00{node}\x00{caller_extent}"


def target_identity(caller: str, node: str) -> str:
    return f"{caller}\x00{node}"


def defs_row(defs: ReachingDefs) -> _Row:
    """One reaching-definition row, identified by what a flow joins on.

    The program is part of that identity: node ids and extent texts are paragraph
    and field names, which repeat across programs, and an identity without it kept
    the first program's row and dropped every other's.
    """
    return (
        defs_identity(defs.program, defs.node, defs.extent),
        json.dumps(
            {
                "program": defs.program,
                "node": defs.node,
                "extent": defs.extent,
                "definers": list(defs.definers),
                "values": sorted(
                    value.decode("utf-8", errors="replace")
                    for value in defs.held.values
                ),
                "reasons": sorted(reason.value for reason in defs.held.reasons),
            }
        ),
    )


def sink_row(sink: ProgramSink) -> _Row:
    return (
        sink_identity(sink),
        json.dumps(
            {
                "program": sink.program,
                "node": sink.node,
                "sink": sink.sink,
                "source_extent": sink.source_extent,
                "definers": list(sink.definers),
            }
        ),
    )


def alias_row(alias: CommareaAlias) -> _Row:
    """One alias, keyed by the site and the caller window it shares.

    One commarea name can resolve to more than one caller cell -- not because a
    group is several cells, it is one, but because the same name can be declared in
    more than one record. The window is in the key so those cells stay apart where
    they land on different bytes, and collapse where they do not. Two cells that
    report one window produce a byte-identical row, which the keep-first dedupe
    drops, rightly: there is one window there to report and not two.
    """
    return (
        alias_identity(alias.caller, alias.node, alias.caller_extent),
        json.dumps(
            {
                "caller": alias.caller,
                "node": alias.node,
                "transfer": alias.transfer,
                "callee": alias.callee,
                "caller_extent": alias.caller_extent,
                "callee_extent": alias.callee_extent,
                "returns": alias.returns,
                "reason": alias.reason,
            }
        ),
    )


def target_fields(
    target: ResolvedTarget,
) -> dict[str, str | list[str] | dict[str, str | list[str]]]:
    """One dynamic site's row fields, before they are written as text. A file site
    also carries its operand's fact, which the combine walks back from."""
    return _with_operand(
        target,
        {
            "caller": target.caller,
            "node": target.node,
            "kind": target.kind.value,
            "transfer": target.transfer,
            "expression": target.expression,
            "candidates": list(target.candidates),
            "reasons": [reason.value for reason in target.reasons],
            "dropped": list(target.dropped),
        },
    )


def _with_operand(
    target: ResolvedTarget, fields: Mapping[str, str | list[str]]
) -> dict[str, str | list[str] | dict[str, str | list[str]]]:
    if target.kind is not TargetKind.FILE:
        return {**fields}
    return {**fields, "operand": fact_dict(target.operand)}


def target_row(target: ResolvedTarget) -> _Row:
    """One dynamic call site's row, identified by its caller and the node that names it.

    Every site is a row, including one that resolved to nothing -- a reader can then
    tell "we looked and could not say" from "there is no such site", which an absent
    row cannot express. Reasons serialise as their enum values; the enum is the type
    and the string is the wire.
    """
    return (
        target_identity(target.caller, target.node),
        json.dumps(target_fields(target)),
    )


class JsonlWriter:
    """One JSON object per line, deduped keep-first on a caller-chosen key.

    Rows arrive already serialised because the tables have unrelated shapes and a
    signature wide enough for all of them would be a blob with extra steps.

    Opened and closed through ``jsonl_writer`` rather than by implementing the
    context-manager protocol itself: ``__exit__`` takes an exception type, an
    exception and a traceback, each of which may be absent, and the repo's lint
    rules admit neither ``object`` nor a ``| None`` union to say so.
    """

    def __init__(self, path: Path) -> None:
        self._written = FirstSighting()
        self._tmp = path.with_suffix(path.suffix + ".tmp")
        self._path = path
        self._file = self._tmp.open("w")

    def add_row(self, key: str, row: str) -> None:
        if not self._written.first_time(key):
            return
        self._file.write(row + "\n")

    def add_rows(self, rows: Iterable[_Row]) -> None:
        for key, row in rows:
            self.add_row(key, row)

    def close(self) -> None:
        self._file.close()
        self._tmp.rename(self._path)

    def abandon(self) -> None:
        self._file.close()


@contextmanager
def jsonl_writer(path: Path) -> Iterator[JsonlWriter]:
    """The ``with`` form of ``JsonlWriter``: published on a clean exit only.

    A block that raises leaves its rows in the .tmp and nothing at the path, as
    ``graph_writer`` does: renamed into place, a partial table would read as
    complete to every consumer.
    """
    writer = JsonlWriter(path)
    try:
        yield writer
    except BaseException:
        writer.abandon()
        raise
    writer.close()
