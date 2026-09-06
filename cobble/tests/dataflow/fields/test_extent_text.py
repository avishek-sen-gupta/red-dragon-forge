"""The wire form for one extent, and the way back from it."""

from __future__ import annotations

from cobble.dataflow.fields.extent_text import NO_RANGE, byte_range, extent_text
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _extent(start: int, length: int, precision: Precision, name: str) -> FieldExtent:
    return FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=start,
        length=length,
        precision=precision,
        field_name=name,
    )


def test_an_exact_extent_keeps_the_bare_form():
    assert (
        extent_text(_extent(4, 4, Precision.EXACT, "WS-B"))
        == "WS-B@working_storage[4:8]"
    )


def test_a_clamped_extent_is_marked_so_a_reader_cannot_read_it_as_a_must_write():
    """A computed subscript lands somewhere in the range and nothing knows where.

    ``FieldExtent.__str__`` drops the precision, so a consumer joining on the bare
    text reads a may-write as a definite one -- and the whole byte-wise
    correspondence with the other operand rests on the target being exact.
    """
    assert (
        extent_text(_extent(0, 12, Precision.CLAMPED, "WS-T"))
        == "WS-T@working_storage[0:12]~"
    )


def test_the_mark_survives_the_round_trip():
    clamped = byte_range(
        extent_text(_extent(0, 12, Precision.CLAMPED, "WS-T")), "PROGA"
    )
    assert not clamped.exact
    assert (clamped.start, clamped.end, clamped.name) == (0, 12, "WS-T")


def test_a_source_that_is_not_storage_parses_to_no_range():
    """An origin -- a literal, a file, a callee -- is written as an empty string.

    A sentinel rather than an absent value, and not a zero-length range at offset
    zero either: that is still a range, and a query counting touching at a
    boundary would match it against the first field of working storage.
    """
    assert byte_range("", "PROGA") is NO_RANGE
    assert byte_range("%CALL:OTHER", "PROGA") is NO_RANGE
    assert not NO_RANGE.overlaps(byte_range("WS-A@working_storage[0:4]", "PROGA"))


def test_two_members_ranges_over_the_same_offsets_are_not_comparable():
    """Byte offsets are region coordinates, and a region is one program's section.

    Comparing them without the program is how a transitive walk leaks into members
    it was never asked about.
    """
    here = byte_range("WS-A@working_storage[0:4]", "PROGA")
    elsewhere = byte_range("WS-A@working_storage[0:4]", "PROGB")

    assert not here.overlaps(elsewhere)
    assert here.overlaps(byte_range("REC@working_storage[0:8]", "PROGA"))


def test_covering_is_directional_and_overlapping_is_not():
    group = byte_range("REC@working_storage[0:8]", "PROGA")
    child = byte_range("WS-B@working_storage[4:8]", "PROGA")
    apart = byte_range("WS-C@working_storage[8:12]", "PROGA")

    assert group.covers(child)
    assert not child.covers(group)
    assert child.overlaps(group) and group.overlaps(child)
    assert not group.overlaps(apart)
