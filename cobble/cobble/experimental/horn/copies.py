"""The writes that move a source's bytes, or their digits, unchanged, and where each target byte comes from."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.state import EMPTY
from cobble.dataflow.fields.transfer import HANDLED, Statement, Write, writes_of
from cobble.experimental.horn.program import Program
from cobol_asg.cobol_statements import MoveStatement
from cobol_asg.ref_mod import (
    FunctionCallOperand,
    RefModLiteral,
    RefModOperand,
    RefModReference,
)
from cobol_memory.field_extent import FieldExtent, Precision

EIBCALEN = "EIBCALEN"


@dataclass(frozen=True)
class Copy:
    """``start`` is the source byte that lands on the target's first byte; with
    ``digits`` only each byte's digit half lands; with ``within`` a byte lands
    only while EIBCALEN exceeds its position in the target, and past that the
    sender has run out."""

    target: FieldExtent
    source: FieldExtent
    start: int
    digits: bool
    within: bool = False

    def source_of(self, offset: int) -> int:
        byte = self.start + offset - self.target.start
        return byte if self.source.start <= byte < self.source.end else -1


def copy_of(write: Write) -> tuple[Copy, ...]:
    if (
        write.weak
        or write.target.precision is not Precision.EXACT
        or not write.copy_start
        or len(write.sources) != 1
    ):
        return ()
    (source,) = write.sources
    if (
        not source.origin.is_storage
        or source.extent.precision is not Precision.EXACT
        or source.extent.may_alias(write.target)
    ):
        return ()
    return (Copy(write.target, source.extent, write.copy_start[0], write.digits),)


def copies_of(statement: Statement, write: Write) -> tuple[Copy, ...]:
    return copy_of(write) or _received(statement, write)


def _received(statement: Statement, write: Write) -> tuple[Copy, ...]:
    """MOVE X(1:EIBCALEN) TO Y, the way a program takes in its commarea."""
    if not isinstance(statement, MoveStatement) or not _calen_long(statement.source):
        return ()
    if not _whole_target(write):
        return ()
    (source,) = write.sources
    return (Copy(write.target, source.extent, source.extent.start, False, True),)


def _whole_target(write: Write) -> bool:
    return (
        not write.weak
        and write.target.precision is Precision.EXACT
        and len(write.sources) == 1
        and not any(s.extent.may_alias(write.target) for s in write.sources)
    )


def _calen_long(source: RefModOperand | FunctionCallOperand) -> bool:
    if not isinstance(source, RefModOperand):
        return False
    length = source.ref_mod_length
    if not isinstance(length, RefModReference):
        return False
    return source.ref_mod_start == RefModLiteral("1") and _calen(length)


def _calen(length: RefModReference) -> bool:
    return length.name == EIBCALEN and not length.qualifiers


def program_copies(program: Program) -> tuple[Copy, ...]:
    return tuple(
        copy
        for node, statement in program.statements.items()
        if isinstance(statement, HANDLED)
        for write in writes_of(statement, node, program.index, EMPTY)
        for copy in copies_of(statement, write)
    )
