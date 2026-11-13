"""The state the encoding follows: one segment per run of bytes a test, a question or a copy into them reads, then EIBCALEN and the marks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce

import z3
from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.srccfg.cfg import Atom, Cfg, NodeKind
from cobble.experimental.horn.context import Context
from cobble.experimental.horn.copies import EIBCALEN, Copy, program_copies
from cobble.experimental.horn.entries import Entries, entries_of
from cobble.experimental.horn.every_test import EVERY_TEST
from cobble.experimental.horn.kept_tests import KeptTests
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.segment import Segment
from cobol_asg.cobol_types import CobolDataCategory
from cobol_asg.pic_parser import parse_pic
from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId

Place = tuple[RegionId, int]

COMPARISONS = ("==", "!=")
ALPHANUMERIC = frozenset("XA")
DISPLAY = ("", "DISPLAY")
CALEN_BYTES = 2
MARK_BYTES = 1


@dataclass(frozen=True)
class Storage:
    """The program's layout, and what the state holds: the segments of it, then
    EIBCALEN when ``eib``, then one byte per mark, 1 once its point has run, then
    one byte per outcome mark and one per entry mark. ``kept`` says which tests
    the encoding keeps."""

    index: CellIndex
    segments: tuple[Segment, ...]
    eib: bool = False
    marks: tuple[Point, ...] = ()
    kept: KeptTests = EVERY_TEST
    outcomes: tuple[str, ...] = ()
    entries: tuple[Entries, ...] = ()

    @property
    def widths(self) -> tuple[int, ...]:
        return (
            *(segment.length for segment in self.segments),
            *((CALEN_BYTES,) if self.eib else ()),
            *((MARK_BYTES,) * (len(self.marks) + len(self.outcomes))),
            *((MARK_BYTES,) * len(self.entries)),
        )

    def calen(self, state: Sequence[z3.BitVecRef]) -> z3.BitVecRef:
        return state[len(self.segments)]

    def mark(self, point: Point, state: Sequence[z3.BitVecRef]) -> z3.BitVecRef:
        if point not in self.marks:
            raise ValueError(f"{point} is not marked")
        return state[len(self.segments) + int(self.eib) + self.marks.index(point)]

    def outcome(self, test: str, state: Sequence[z3.BitVecRef]) -> z3.BitVecRef:
        if test not in self.outcomes:
            raise ValueError(f"{test} has no outcome mark")
        return state[self._first_outcome + self.outcomes.index(test)]

    def entry(self, range_: Context, state: Sequence[z3.BitVecRef]) -> z3.BitVecRef:
        return state[self._first_outcome + len(self.outcomes) + self.entered(range_)]

    def entered(self, range_: Context) -> int:
        found = tuple(n for n, e in enumerate(self.entries) if e.range == range_)
        if not found:
            raise ValueError(f"{range_} has no entry mark")
        return found[0]

    @property
    def _first_outcome(self) -> int:
        return len(self.segments) + int(self.eib) + len(self.marks)

    def field(self, name: str) -> tuple[FieldExtent, ...]:
        """The one alphanumeric extent ``name`` denotes, written whole with no
        subscript, or nothing."""
        cells = self.index.cells_named(name, (), 0)
        if len(cells) != 1 or not _alphanumeric(cells[0].pic, cells[0].usage):
            return ()
        return (self.index.extent_of(cells[0]),)

    def numeral(self, name: str) -> tuple[FieldExtent, ...]:
        """The one unsigned integer zoned extent ``name`` denotes, written whole with
        no subscript, or nothing."""
        cells = self.index.cells_named(name, (), 0)
        if len(cells) != 1 or not unsigned_integer(cells[0].pic, cells[0].usage):
            return ()
        return (self.index.extent_of(cells[0]),)

    def whole(self, name: str) -> tuple[FieldExtent, ...]:
        """The extent of the one cell ``name`` denotes with no subscript, of any
        picture, or nothing."""
        cells = self.index.cells_named(name, (), 0)
        return (self.index.extent_of(cells[0]),) if len(cells) == 1 else ()

    def tracked(self, name: str) -> tuple[FieldExtent, ...]:
        return tuple(extent for extent in self.field(name) if self.locate(extent) >= 0)

    def counted(self, name: str) -> tuple[FieldExtent, ...]:
        return tuple(
            extent for extent in self.numeral(name) if self.locate(extent) >= 0
        )

    def locate(self, extent: FieldExtent) -> int:
        return next(
            (n for n, segment in enumerate(self.segments) if segment.holds(extent)), -1
        )

    def placed(self, region: RegionId, offset: int) -> int:
        return next(
            (
                n
                for n, segment in enumerate(self.segments)
                if segment.region is region and segment.start <= offset < segment.end
            ),
            -1,
        )

    def value(self, extent: FieldExtent, state: Sequence[z3.BitVecRef]) -> z3.BitVecRef:
        n = self.locate(extent)
        return self.segments[n].bytes_of(extent, state[n])


def _alphanumeric(pic: str, usage: str) -> bool:
    """A group, or a picture of X and A only: PIC 9 has no letters and is a number."""
    letters = frozenset(c for c in pic.upper() if c.isalpha())
    kind = letters <= ALPHANUMERIC and (bool(letters) or not pic)
    return usage.upper() in DISPLAY and kind


def unsigned_integer(pic: str, usage: str) -> bool:
    if not pic or usage.upper() not in DISPLAY:
        return False
    kind = parse_pic(pic, usage)
    return (
        kind.category is CobolDataCategory.ZONED_DECIMAL
        and not kind.signed
        and kind.decimal_digits == 0
        and kind.char_positions == kind.total_digits
    )


def integer(text: str) -> bool:
    """An unsigned integer literal, as the CFG writes one."""
    return text.isascii() and text.isdigit()


def storage_of(
    program: Program,
    watched: Sequence[str],
    marks: Sequence[Point] = (),
    extra: frozenset[Place] = frozenset(),
    kept: KeptTests = EVERY_TEST,
    outcomes: Sequence[str] = (),
    entries: Sequence[Context] = (),
) -> Storage:
    """``extra`` are bytes to follow beside the ones the program's tests read: a
    later task's tests, reading what this task hands it."""
    probe = Storage(program.index, ())
    comparisons = tuple(a for a in _comparisons(program.cfg) if kept.keeps(a))
    tested = tuple(extent for atom in comparisons for extent in _tested(probe, atom))
    places = _closed(
        extra
        | frozenset(
            place
            for extent in (*tested, *_watched(probe, watched))
            for place in _places(extent)
        ),
        program_copies(program),
    )
    eib = not probe.whole(EIBCALEN) and any(
        atom.left == EIBCALEN and integer(atom.right) for atom in comparisons
    )
    return Storage(
        program.index,
        _segments(places),
        eib,
        tuple(marks),
        kept,
        tuple(outcomes),
        tuple(entries_of(program.cfg, range_) for range_ in entries),
    )


def _tested(probe: Storage, atom: Atom) -> tuple[FieldExtent, ...]:
    numbers = probe.numeral(atom.left) if integer(atom.right) else ()
    return (
        *numbers,
        *(e for name in (atom.left, atom.right) for e in probe.field(name)),
    )


def _watched(probe: Storage, names: Sequence[str]) -> tuple[FieldExtent, ...]:
    found = tuple((name, probe.whole(name)) for name in names)
    missing = tuple(name for name, extents in found if not extents)
    if missing:
        raise ValueError(f"{missing[0]} is not one field")
    return tuple(extent for _, extents in found for extent in extents)


def _places(extent: FieldExtent) -> tuple[Place, ...]:
    return tuple((extent.region, offset) for offset in range(extent.start, extent.end))


def _closed(places: frozenset[Place], copies: Sequence[Copy]) -> frozenset[Place]:
    """The places, and the source byte of every copy into one of them, until no
    copy adds another."""
    fed = frozenset(
        (copy.source.region, byte)
        for copy in copies
        for region, offset in _places(copy.target)
        if (region, offset) in places
        for byte in (copy.source_of(offset),)
        if byte >= 0
    )
    grown = places | fed
    return grown if grown == places else _closed(grown, copies)


def _segments(places: frozenset[Place]) -> tuple[Segment, ...]:
    ordered = sorted(places, key=lambda place: (place[0].value, place[1]))
    return reduce(_extended, ordered, ())


def _extended(done: tuple[Segment, ...], place: Place) -> tuple[Segment, ...]:
    region, offset = place
    if done and done[-1].region is region and done[-1].end == offset:
        last = done[-1]
        return (*done[:-1], Segment(region, last.start, offset + 1))
    return (*done, Segment(region, offset, offset + 1))


def _comparisons(cfg: Cfg) -> tuple[Atom, ...]:
    return tuple(
        node.atom
        for node in cfg.nodes
        if node.kind is NodeKind.TEST
        and node.atom.plain
        and node.atom.op in COMPARISONS
    )
