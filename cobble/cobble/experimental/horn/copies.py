"""The writes that move a source's bytes, or their digits, unchanged, and where each target byte comes from."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.state import EMPTY
from cobble.dataflow.fields.transfer import HANDLED, Write, writes_of
from cobble.experimental.horn.program import Program
from cobol_memory.field_extent import FieldExtent, Precision


@dataclass(frozen=True)
class Copy:
    """``start`` is the source byte that lands on the target's first byte; with
    ``digits`` only each byte's digit half lands."""

    target: FieldExtent
    source: FieldExtent
    start: int
    digits: bool

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


def program_copies(program: Program) -> tuple[Copy, ...]:
    return tuple(
        copy
        for node, statement in program.statements.items()
        if isinstance(statement, HANDLED)
        for write in writes_of(statement, node, program.index, EMPTY)
        for copy in copy_of(write)
    )
