"""The bytes the encoding follows: one segment per run of bytes some test reads."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import groupby

import z3
from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.srccfg.cfg import Atom, Cfg, NodeKind
from cobble.experimental.horn.segment import Segment
from cobol_memory.field_extent import FieldExtent

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

    def tracked(self, name: str) -> tuple[FieldExtent, ...]:
        return tuple(extent for extent in self.field(name) if self.locate(extent) >= 0)

    def locate(self, extent: FieldExtent) -> int:
        return next(
            (n for n, segment in enumerate(self.segments) if segment.holds(extent)), -1
        )

    def value(self, extent: FieldExtent, state: Sequence[z3.BitVecRef]) -> z3.BitVecRef:
        n = self.locate(extent)
        return self.segments[n].bytes_of(extent, state[n])


def _alphanumeric(pic: str, usage: str) -> bool:
    letters = frozenset(c for c in pic.upper() if c.isalpha())
    return usage.upper() in DISPLAY and letters <= ALPHANUMERIC


def storage_of(cfg: Cfg, index: CellIndex) -> Storage:
    probe = Storage(index, ())
    extents = tuple(
        extent
        for atom in _comparisons(cfg)
        for name in (atom.left, atom.right)
        for extent in probe.field(name)
    )
    return Storage(index, _merged(extents))


def _comparisons(cfg: Cfg) -> tuple[Atom, ...]:
    return tuple(
        node.atom
        for node in cfg.nodes
        if node.kind is NodeKind.TEST
        and node.atom.plain
        and node.atom.op in COMPARISONS
    )


def _merged(extents: Sequence[FieldExtent]) -> tuple[Segment, ...]:
    ordered = sorted(extents, key=lambda e: (e.region.value, e.start, e.end))
    return tuple(
        segment
        for _, group in groupby(ordered, key=lambda e: e.region)
        for segment in reduce(_joined, group, ())
    )


def _joined(done: tuple[Segment, ...], extent: FieldExtent) -> tuple[Segment, ...]:
    if done and done[-1].region is extent.region and extent.start <= done[-1].end:
        last = done[-1]
        return (*done[:-1], Segment(last.region, last.start, max(last.end, extent.end)))
    return (*done, Segment(extent.region, extent.start, extent.end))
