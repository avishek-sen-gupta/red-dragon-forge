"""Combine's link windows as dep rows, one per field a window carries, with the writes that reach each side."""

from __future__ import annotations

from dataclasses import replace
from functools import cache
from pathlib import Path

from cobble.dataflow.combine.link_row import LinkRow
from cobble.dataflow.fields.crossing import Crossing
from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.build_corpus import JUMPS_FILE, MEMBERS_DIR
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_from_row
from cobol_memory.region_id import RegionId

_Part = tuple[ByteRange, Fact]


@cache
def _jumps(path: Path) -> tuple[Jump, ...]:
    """A program the out-dir holds no member for jumps nowhere, as one outside the
    corpus does."""
    if not path.is_file():
        return ()
    return tuple(
        jump_from_row(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _parts(jump: Jump, window: ByteRange) -> tuple[_Part, ...]:
    """Each field of the jump's areas inside the window, clipped to it."""
    return tuple(
        (
            replace(
                found,
                start=max(found.start, window.start),
                end=min(found.end, window.end),
            ),
            fact,
        )
        for area in jump.areas
        for fact in area.fields
        for found in (byte_range(fact.extent, window.program),)
        if found.overlaps(window)
    )


def _across(part: ByteRange, near: ByteRange, far: ByteRange) -> ByteRange:
    """The far window's bytes that a part of the near window binds to."""
    return replace(
        far,
        start=far.start + part.start - near.start,
        end=far.start + part.end - near.start,
        exact=part.exact,
    )


def _from_entry(part: ByteRange, facts: tuple[Fact, ...]) -> bool:
    """Linkage bytes that may still hold what the program was entered with."""
    return part.region == RegionId.LINKAGE.value and any(
        UnresolvedReason.INBOUND_LINKAGE in fact.reasons for fact in facts
    )


def _row(
    link: LinkRow,
    crossing: Crossing,
    written: ByteRange,
    part: ByteRange,
    facts: tuple[Fact, ...],
) -> DepRow:
    return DepRow(
        program=written.program,
        via="",
        target=written,
        origin="",
        source=part,
        site=f"{link.caller}/{link.node}",
        definers=tuple(
            dict.fromkeys(
                f"{part.program}/{writer}" for fact in facts for writer in fact.writers
            )
        ),
        sink="",
        entry=_from_entry(part, facts),
        crossing=crossing,
    )


def _entered(link: LinkRow, members: Path) -> tuple[DepRow, ...]:
    """The caller's bytes into the callee, each field with the writes reaching the call."""
    caller = byte_range(link.caller_extent, link.caller)
    callee = byte_range(link.callee_extent, link.callee)
    return tuple(
        _row(link, Crossing.ENTERED, _across(part, caller, callee), part, (fact,))
        for jump in _jumps(members / link.caller / JUMPS_FILE)
        if jump.node == link.node
        for part, fact in _parts(jump, caller)
    )


def _distinct(parts: tuple[ByteRange, ...]) -> tuple[ByteRange, ...]:
    return tuple(part for n, part in enumerate(parts) if part not in parts[:n])


def _returned(link: LinkRow, members: Path) -> tuple[DepRow, ...]:
    """The callee's bytes back to the caller, each field with the writes reaching any
    of the callee's exits."""
    caller = byte_range(link.caller_extent, link.caller)
    callee = byte_range(link.callee_extent, link.callee)
    found = tuple(
        found
        for jump in _jumps(members / link.callee / JUMPS_FILE)
        if jump.kind is JumpKind.EXIT
        for found in _parts(jump, callee)
    )
    return tuple(
        _row(
            link,
            Crossing.RETURNED,
            _across(part, callee, caller),
            part,
            tuple(fact for at, fact in found if at == part),
        )
        for part in _distinct(tuple(at for at, _fact in found))
    )


def crossing_rows(fixpoint_dir: Path, link: LinkRow) -> tuple[DepRow, ...]:
    members = fixpoint_dir / MEMBERS_DIR
    returned = _returned(link, members) if link.returns else ()
    return (*_entered(link, members), *returned)
