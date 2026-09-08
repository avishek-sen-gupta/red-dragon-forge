"""The artefact's wire form for a byte extent, and the way back from it.

Written here rather than on ``FieldExtent`` because ``FieldExtent.__str__`` drops
``precision``, and a consumer that cannot tell a must-write from a may-write
reads a computed-subscript write as though the analysis knew which occurrence it
landed in. EXACT is the common case and keeps the bare form; CLAMPED carries a
mark. Nothing else about an extent is added, because everything else about it --
which fields it covers, whether it is a group, what usage it was declared with
-- is a property of the layout and belongs in the declared-extents table, once
per field, rather than on every range that happens to fall inside it.

A parse needs the program the text came from. Byte offsets are region
coordinates and a region is one program's section, so two members'
``working_storage[0:8]`` name different bytes: comparing them without the
program is how a transitive walk leaks into members it was never asked about.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from cobol_memory.field_extent import FieldExtent, Precision

CLAMPED_MARK = "~"

_PATTERN = re.compile(
    r"^(?P<name>.*)@(?P<region>[a-z_]+)\[(?P<start>\d+):(?P<end>\d+)\](?P<clamped>~?)$"
)


def extent_text(extent: FieldExtent) -> str:
    """One extent as the artefact spells it, precision included."""
    if extent.precision is Precision.CLAMPED:
        return f"{extent}{CLAMPED_MARK}"
    return str(extent)


@dataclass(frozen=True)
class ByteRange:
    """One extent as a query compares them: program-scoped and half-open.

    ``known`` False is the parse of a source that is not storage at all -- a
    literal, a file, a callee -- which the artefact writes as an empty string. A
    sentinel rather than an absent value, so every caller compares ranges the
    same way and an unparseable text can never be mistaken for offset zero.

    ``exact`` False is a CLAMPED extent: the access lands somewhere inside this
    range and nothing knows where. It may be read as a may-write, and byte-wise
    correspondence with the other operand does not hold across it.
    """

    program: str = ""
    region: str = ""
    start: int = 0
    end: int = 0
    name: str = ""
    exact: bool = True
    known: bool = False

    @property
    def length(self) -> int:
        return self.end - self.start

    def _comparable(self, other: ByteRange) -> bool:
        return (
            self.known
            and other.known
            and self.program == other.program
            and self.region == other.region
        )

    def overlaps(self, other: ByteRange) -> bool:
        return (
            self._comparable(other)
            and self.start < other.end
            and other.start < self.end
        )

    def covers(self, other: ByteRange) -> bool:
        return (
            self._comparable(other)
            and self.start <= other.start
            and other.end <= self.end
        )

    def __str__(self) -> str:
        if not self.known:
            return "(not storage)"
        mark = CLAMPED_MARK if not self.exact else ""
        return f"{self.name}@{self.region}[{self.start}:{self.end}]{mark}"


NO_RANGE = ByteRange()


def byte_range_from_dict(
    row: Mapping[str, str | int | bool], program: str
) -> ByteRange:
    """A JSONL extent object back to a comparable range."""
    return ByteRange(
        program=program,
        region=str(row.get("region", "")),
        start=int(str(row.get("start", 0))),
        end=int(str(row.get("end", 0))),
        name=str(row.get("field", "")),
        exact=not row.get("clamped", False),
        known=True,
    )


def byte_range(text: str, program: str) -> ByteRange:
    """The wire form back to a comparable range; NO_RANGE if it is not one."""
    found = _PATTERN.match(text)
    if not found:
        return NO_RANGE
    return ByteRange(
        program=program,
        region=found["region"],
        start=int(found["start"]),
        end=int(found["end"]),
        name=found["name"],
        exact=not found["clamped"],
        known=True,
    )
