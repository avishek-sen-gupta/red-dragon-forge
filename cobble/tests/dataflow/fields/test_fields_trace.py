"""The path walk: its stack rules on graphs built here, its crossing on a real parse.

Two halves, because they fail for different reasons. The stack rules -- unroll a
loop once, let a paragraph PERFORMed twice run twice, take only your own RETURN
edge -- are decided by the walk alone, so they are asserted against CFGs written
out in this file where every node id is chosen here. The crossing is decided by
the bridge's layout arithmetic, which no hand-built extent can stand in for: a
rebase that is off by a byte agrees with a fixture and disagrees with COBOL.
"""

from __future__ import annotations

from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.state import Source, write
from cobble.dataflow.fields.trace import (
    NO_WINDOW,
    _extent_at,
    _rebased,
    _seeded,
    _window,
)
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _extent(region: RegionId, start: int, length: int, name: str) -> FieldExtent:
    return FieldExtent(
        region=region,
        start=start,
        length=length,
        precision=Precision.EXACT,
        field_name=name,
    )


def _sourced(name: str, node: str) -> frozenset[Source]:
    return frozenset(
        {
            Source(
                origin="",
                extent=_extent(RegionId.WORKING_STORAGE, 0, 4, name),
                node=node,
            )
        }
    )


def test_the_region_text_round_trips_through_the_enum_that_wrote_it():
    """``FieldExtent.__str__`` spells the region as the enum's own value, so
    ``RegionId(text)`` is the way back and no mapping table is needed."""
    found = _extent_at("WS-AREA@working_storage[8:20]", "TPROGA")

    assert found.region is RegionId.WORKING_STORAGE
    assert (found.start, found.length) == (8, 12)
    assert found.field_name == "WS-AREA"
    assert found.precision is Precision.EXACT


def test_a_text_that_is_not_an_extent_parses_to_a_length_of_nothing():
    """A dead-end alias row carries a reason where the extents would be. Zero
    length is what makes that safe to carry in an extent-shaped slot: may_alias
    and must_cover both reject a non-positive length."""
    assert not _extent_at("", "TPROGA").length
    assert not _extent_at("callee-not-in-cache", "TPROGA").length


def test_a_row_carrying_a_reason_yields_no_window():
    row = CommareaAlias(
        caller="TPROGA", node="MAIN-PARA/2", transfer="LINK", reason="dynamic-target"
    )

    assert _window(row, "") == NO_WINDOW


def test_a_row_carrying_both_layouts_yields_the_window_they_share():
    row = CommareaAlias(
        caller="TPROGA",
        node="MAIN-PARA/2",
        transfer="LINK",
        callee="TPROGB",
        caller_extent="WS-AREA@working_storage[8:20]",
        callee_extent="DFHCOMMAREA@linkage[0:12]",
        returns=True,
    )
    found = _window(row, "TPROGB")

    assert found.known
    assert found.caller == "TPROGA"
    assert found.caller_extent.start == 8
    assert found.callee_extent.region is RegionId.LINKAGE
    assert found.caller_extent.length == found.callee_extent.length


def test_a_rebase_shifts_by_the_two_windows_offsets_and_renames_the_bytes():
    """Caller byte ``source.start + k`` IS callee byte ``target.start + k``. The
    rebased extent takes the target record's name, because spelling the caller's
    field name inside the callee's region names a field that is not there."""
    window_in = _extent(RegionId.WORKING_STORAGE, 8, 12, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 12, "DFHCOMMAREA")
    found = _rebased(
        _extent(RegionId.WORKING_STORAGE, 12, 4, "WS-B"), window_in, window_out
    )

    assert found.region is RegionId.LINKAGE
    assert (found.start, found.length) == (4, 4)
    assert found.field_name == "DFHCOMMAREA"


def test_a_rebase_clips_to_the_window_rather_than_claiming_past_it():
    """Bytes outside the shared window are not shared storage. A rebase that kept
    them would report the callee as addressing the caller's whole record."""
    window_in = _extent(RegionId.WORKING_STORAGE, 8, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    found = _rebased(
        _extent(RegionId.WORKING_STORAGE, 4, 12, "WS-WIDE"), window_in, window_out
    )

    assert (found.start, found.length) == (0, 8)


def test_seeding_carries_provenance_across_unchanged_and_credits_no_node():
    """A binding, not a flow: nothing converts and nothing pads, so the sources
    cross intact and no node is recorded as having written them."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    held = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-KEY"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )
    found = _seeded(held, window_in, window_out)

    ((extent, sources),) = tuple(found.items())
    assert extent.region is RegionId.LINKAGE
    assert (extent.start, extent.length) == (0, 4)
    assert tuple(one.node for one in sources) == ("TPROGA/MAIN-PARA/0",)


def test_seeding_leaves_behind_whatever_the_window_does_not_reach():
    """Only the shared bytes are bound. Storage outside the commarea is the
    caller's alone and has no address in the callee at all."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    held = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 40, 4, "WS-PRIVATE"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )

    assert not _seeded(held, window_in, window_out)


def test_two_caller_extents_clipping_to_one_window_range_keep_both_provenances():
    """A union, not a dict comprehension. Two extents can clip to the same shared
    range -- a record and a redefinition of it -- and keying a comprehension on the
    rebased extent would drop one of them silently."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 4, "DFHCOMMAREA")
    first = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-KEY"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )
    both = {
        **first,
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-ALIAS"): _sourced(
            "WS-OTHER", "TPROGA/MAIN-PARA/1"
        ),
    }
    found = _seeded(both, window_in, window_out)

    ((_extent_out, sources),) = tuple(found.items())
    assert {one.node for one in sources} == {
        "TPROGA/MAIN-PARA/0",
        "TPROGA/MAIN-PARA/1",
    }
