"""The fields whose values the encoding follows exactly: one alphanumeric extent, compared by a test."""

from collections.abc import Sequence
from dataclasses import dataclass

from cobble.dataflow.fields.extent_line import ExtentLine
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.srccfg.cfg import Cfg, NodeKind

COMPARISONS = ("==", "!=")


@dataclass(frozen=True)
class Tracked:
    name: str
    length: int
    extent: ByteRange


@dataclass(frozen=True)
class Declared:
    name: str
    pic: str
    usage: str
    extent: ByteRange


def declarations(extents: Sequence[ExtentLine]) -> tuple[Declared, ...]:
    return tuple(
        Declared(name, pic, usage, byte_range(text, row.program))
        for row in extents
        for name, pic, usage, text in zip(
            row.names, row.pics, row.usages, row.extents, strict=True
        )
    )


def _compared(cfg: Cfg) -> frozenset[str]:
    atoms = tuple(
        node.atom
        for node in cfg.nodes
        if node.kind is NodeKind.TEST and node.atom.op in COMPARISONS
    )
    return frozenset(name for atom in atoms for name in (atom.left, atom.right))


def _trackable(name: str, declared: Sequence[Declared]) -> bool:
    own = tuple(entry for entry in declared if entry.name == name)
    return (
        len(own) == 1
        and own[0].pic.startswith("X")
        and own[0].usage == "DISPLAY"
        and own[0].extent.known
    )


def tracked_fields(cfg: Cfg, extents: Sequence[ExtentLine]) -> tuple[Tracked, ...]:
    declared = declarations(extents)
    return tuple(
        Tracked(entry.name, entry.extent.length, entry.extent)
        for entry in declared
        if entry.name in _compared(cfg) and _trackable(entry.name, declared)
    )
