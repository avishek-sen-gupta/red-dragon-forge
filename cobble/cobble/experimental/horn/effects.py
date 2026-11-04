"""What one node does to each tracked byte: keeps it, sets it to a known byte, or frees it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce

from cobble.dataflow.fields.extent import operand_extents
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fields.state import EMPTY
from cobble.dataflow.fields.transfer import HANDLED, Write, writes_of
from cobble.experimental.horn.atoms import FIGURATIVES
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.segment import Segment
from cobble.experimental.horn.storage import Storage
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent, Precision

NO_WRITES = frozenset(
    {
        "IfStatement",
        "EvaluateStatement",
        "WhenStatement",
        "WhenOtherStatement",
        "DisplayStatement",
        "GotoStatement",
        "StopRunStatement",
        "GobackStatement",
        "ExitProgramStatement",
        "PerformStatement",
        "ContinueStatement",
        "ExitStatement",
        "NextSentenceStatement",
        "AlterStatement",
        "CancelStatement",
        "OpenStatement",
        "CloseStatement",
        "StartStatement",
        "DeleteStatement",
        "SortStatement",
        "MergeStatement",
    }
)

FILE_IO = frozenset(
    {
        "OpenStatement",
        "CloseStatement",
        "ReadStatement",
        "FileRead",
        "WriteStatement",
        "RewriteStatement",
        "StartStatement",
        "DeleteStatement",
        "ReturnStatement",
        "ReleaseStatement",
        "SortStatement",
        "MergeStatement",
    }
)


@dataclass(frozen=True)
class Kept:
    """The byte the node found."""


@dataclass(frozen=True)
class Freed:
    """A byte the node may have changed to anything; ``write`` tells writes apart."""

    write: int


Byte = Kept | Freed | int
KEPT = Kept()


@dataclass(frozen=True)
class Effect:
    """Per segment, what becomes of each of its bytes."""

    bytes: tuple[tuple[Byte, ...], ...]


def nothing(storage: Storage) -> Effect:
    return Effect(tuple((KEPT,) * segment.length for segment in storage.segments))


def everything(storage: Storage) -> Effect:
    return Effect(tuple((Freed(-1),) * segment.length for segment in storage.segments))


def effect_of(program: Program, storage: Storage, node: str) -> Effect:
    if node not in program.statements:
        return _named(program, storage, node, nothing(storage), ())
    statement = program.statements[node]
    kind = type(statement).__name__
    if not isinstance(statement, HANDLED) and kind not in NO_WRITES:
        return everything(storage)
    writes = (
        writes_of(statement, node, program.index, EMPTY)
        if isinstance(statement, HANDLED)
        else ()
    )
    written = reduce(
        lambda done, n: _applied(done, storage, writes[n], n),
        range(len(writes)),
        nothing(storage),
    )
    statused = _statuses(program, storage, kind, written)
    return _named(program, storage, node, statused, tuple(w.target for w in writes))


def _definite(write: Write, storage: Storage) -> tuple[bytes, ...]:
    target = write.target
    if (
        write.weak
        or target.precision is not Precision.EXACT
        or _justified(storage, target)
    ):
        return ()
    values = write.values
    if values.complete and len(values.values) == 1:
        (value,) = values.values
        return (value,) if len(value) == target.length else ()
    return _figurative(write)


def _figurative(write: Write) -> tuple[bytes, ...]:
    origins = tuple(source.origin for source in write.sources)
    if len(origins) != 1 or origins[0].kind is not OriginKind.LITERAL:
        return ()
    fill = FIGURATIVES.get(origins[0].name.strip().upper(), b"")
    return (fill * write.target.length,) if fill else ()


def _justified(storage: Storage, target: FieldExtent) -> bool:
    return any(cell.justified for cell in storage.index.containing(target))


def _applied(done: Effect, storage: Storage, write: Write, n: int) -> Effect:
    value = _definite(write, storage)
    return Effect(
        tuple(
            _laid(bytes_, segment, write.target, value, n)
            for segment, bytes_ in zip(storage.segments, done.bytes, strict=True)
        )
    )


def _laid(
    bytes_: tuple[Byte, ...],
    segment: Segment,
    target: FieldExtent,
    value: tuple[bytes, ...],
    n: int,
) -> tuple[Byte, ...]:
    if not segment.overlaps(target):
        return bytes_
    return tuple(
        _byte_at(old, segment.start + i, target, value, n)
        for i, old in enumerate(bytes_)
    )


def _byte_at(
    old: Byte, offset: int, target: FieldExtent, value: tuple[bytes, ...], n: int
) -> Byte:
    if not target.start <= offset < target.end:
        return old
    if value:
        return value[0][offset - target.start]
    return Freed(n)


def _statuses(program: Program, storage: Storage, kind: str, done: Effect) -> Effect:
    if kind not in FILE_IO:
        return done
    return _freeing(storage, done, program.file_statuses, -2)


def _named(
    program: Program,
    storage: Storage,
    node: str,
    done: Effect,
    covered: Sequence[FieldExtent],
) -> Effect:
    """Every name the CFG says the node writes, freed where no write above
    accounted for it: a statement whose writes the transfer misses still changes
    what its node lists."""
    extents = tuple(
        extent
        for name in program.cfg.node(node).writes
        for extent in operand_extents(RefModOperand(name=name), program.index).extents
    )
    return _freeing(storage, done, extents, -3, covered)


def _freeing(
    storage: Storage,
    done: Effect,
    extents: Sequence[FieldExtent],
    tag: int,
    covered: Sequence[FieldExtent] = (),
) -> Effect:
    return Effect(
        tuple(
            tuple(
                _freed_unless_covered(old, segment, i, extents, covered, tag)
                for i, old in enumerate(bytes_)
            )
            for segment, bytes_ in zip(storage.segments, done.bytes, strict=True)
        )
    )


def _freed_unless_covered(
    old: Byte,
    segment: Segment,
    i: int,
    extents: Sequence[FieldExtent],
    covered: Sequence[FieldExtent],
    tag: int,
) -> Byte:
    offset = segment.start + i
    hit = any(_at(extent, segment, offset) for extent in extents)
    if not hit or any(_at(extent, segment, offset) for extent in covered):
        return old
    return Freed(tag)


def _at(extent: FieldExtent, segment: Segment, offset: int) -> bool:
    return extent.region is segment.region and extent.start <= offset < extent.end
