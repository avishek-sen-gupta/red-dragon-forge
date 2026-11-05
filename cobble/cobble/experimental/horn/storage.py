"""The bytes the encoding follows: one segment per run of bytes a test, a question or a copy into them reads."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce

import z3
from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.srccfg.cfg import Atom, Cfg, NodeKind
from cobble.experimental.horn.copies import Copy, program_copies
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.segment import Segment
from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId

Place = tuple[RegionId, int]

COMPARISONS = ("==", "!=")
ALPHANUMERIC = frozenset("XA")
DISPLAY = ("", "DISPLAY")


@dataclass(frozen=True)
class Storage:
    """The program's layout, and the segments of it the state holds."""

    index: CellIndex
    segments: tuple[Segment, ...]

    def field(self, name: str) -> tuple[FieldExtent, ...]:
        """The one alphanumeric extent ``name`` denotes, written whole with no
        subscript, or nothing."""
        cells = self.index.cells_named(name, (), 0)
        if len(cells) != 1 or not _alphanumeric(cells[0].pic, cells[0].usage):
            return ()
        return (self.index.extent_of(cells[0]),)

    def whole(self, name: str) -> tuple[FieldExtent, ...]:
        """The extent of the one cell ``name`` denotes with no subscript, of any
        picture, or nothing."""
        cells = self.index.cells_named(name, (), 0)
        return (self.index.extent_of(cells[0]),) if len(cells) == 1 else ()

    def tracked(self, name: str) -> tuple[FieldExtent, ...]:
        return tuple(extent for extent in self.field(name) if self.locate(extent) >= 0)

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
    letters = frozenset(c for c in pic.upper() if c.isalpha())
    return usage.upper() in DISPLAY and letters <= ALPHANUMERIC


def storage_of(program: Program, watched: Sequence[str]) -> Storage:
    probe = Storage(program.index, ())
    tested = tuple(
        extent
        for atom in _comparisons(program.cfg)
        for name in (atom.left, atom.right)
        for extent in probe.field(name)
    )
    places = _closed(
        frozenset(
            place
            for extent in (*tested, *_watched(probe, watched))
            for place in _places(extent)
        ),
        program_copies(program),
    )
    return Storage(program.index, _segments(places))


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
