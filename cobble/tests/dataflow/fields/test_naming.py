"""An extent names the smallest field that covers it, deterministically.

Two cells of equal length over one byte range are ordinary -- a group and its
only child, or a REDEFINES view -- so the tie-break has to be total or the same
extent gets two names across runs.
"""

from __future__ import annotations

import pytest
from cobble.dataflow.fields.naming import covering_fields, smallest_covering
from cobble.dataflow.fields.state import NOWHERE
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _extent(start: int, length: int, name: str = "?") -> FieldExtent:
    return FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=start,
        length=length,
        precision=Precision.EXACT,
        field_name=name,
    )


@pytest.fixture
def nested(field):
    """A record whose bytes 8-12 are owned by a group and its only child.

    Child offsets are parent-relative and come from the bridge rather than from
    layout, so every one of them is stated the way the parse cache states it.
    """
    return [
        field(
            1,
            "REC-MASTER",
            offset=0,
            children=[
                field(5, "MST-KEY", "X(8)", offset=0),
                field(
                    5,
                    "MST-BODY",
                    offset=8,
                    children=[field(10, "MST-COUNT", "9(4)", offset=0)],
                ),
            ],
        )
    ]


def test_a_member_extent_names_the_member_not_the_record(program_of, index_of, nested):
    asg = program_of([], data_fields=nested)
    assert smallest_covering(_extent(8, 4), index_of(asg)) == "MST-COUNT"


def test_an_extent_spanning_two_members_names_their_smallest_common_group(
    program_of, index_of, nested
):
    asg = program_of([], data_fields=nested)
    assert smallest_covering(_extent(0, 12), index_of(asg)) == "REC-MASTER"


def test_an_extent_straddling_two_members_names_the_group_that_holds_both(
    program_of, index_of, nested
):
    """Bytes 6-10 belong to no single member, but the record still covers them."""
    asg = program_of([], data_fields=nested)
    assert smallest_covering(_extent(6, 4), index_of(asg)) == "REC-MASTER"


def test_an_extent_past_every_record_falls_back_to_its_own_name(
    program_of, index_of, nested
):
    asg = program_of([], data_fields=nested)
    assert smallest_covering(_extent(64, 4, name="WS-ODD"), index_of(asg)) == "WS-ODD"


def test_the_nowhere_sentinel_keeps_its_synthetic_origin_name(
    program_of, index_of, nested
):
    """A source from outside storage must not acquire a field's name.

    NOWHERE is zero-length, and ``_spans`` is inclusive at both ends, so length
    alone would not save it -- what does is its region, which holds no record.
    """
    asg = program_of([], data_fields=nested)
    assert smallest_covering(NOWHERE, index_of(asg)) == NOWHERE.field_name
    assert covering_fields(NOWHERE, index_of(asg)) == ()


def test_covering_fields_expands_to_every_field_touched_smallest_first(
    program_of, index_of, nested
):
    asg = program_of([], data_fields=nested)
    assert covering_fields(_extent(8, 4), index_of(asg)) == (
        "MST-COUNT",
        "MST-BODY",
        "REC-MASTER",
    )


def test_covering_fields_includes_a_field_the_extent_only_partly_touches(
    program_of, index_of, nested
):
    """Expansion is overlap, not containment: a straddling extent touches both."""
    asg = program_of([], data_fields=nested)
    touched = covering_fields(_extent(6, 4), index_of(asg))
    assert {"MST-KEY", "MST-COUNT"} <= set(touched)


def test_a_redefines_view_appears_in_the_expansion(program_of, index_of, field):
    asg = program_of(
        [],
        data_fields=[
            field(1, "REC-A", offset=0, children=[field(5, "WS-A", "X(4)", offset=0)]),
            field(
                1,
                "REC-B",
                offset=0,
                redefines="REC-A",
                children=[field(5, "WS-ALT", "X(4)", offset=0)],
            ),
        ],
    )
    assert "WS-ALT" in covering_fields(_extent(0, 4), index_of(asg))


def test_an_extent_in_another_region_names_nothing_in_working_storage(
    program_of, index_of, field
):
    """Regions are separate address spaces; an offset alone does not identify bytes."""
    asg = program_of(
        [],
        data_fields=[field(1, "REC-A", offset=0, children=[field(5, "WS-A", "X(4)")])],
        linkage_fields=[
            field(1, "REC-L", offset=0, children=[field(5, "LK-A", "X(4)")])
        ],
    )
    linkage = FieldExtent(
        region=RegionId.LINKAGE,
        start=0,
        length=4,
        precision=Precision.EXACT,
        field_name="?",
    )
    assert smallest_covering(linkage, index_of(asg)) == "LK-A"
    assert covering_fields(linkage, index_of(asg)) == ("LK-A", "REC-L")


def test_a_clamped_extent_still_names_the_table_it_spans(program_of, index_of, field):
    """A computed subscript yields a CLAMPED span; naming must not care."""
    asg = program_of(
        [],
        data_fields=[
            field(
                1,
                "REC-T",
                offset=0,
                children=[field(5, "WS-T", "X(4)", offset=0, occurs=3)],
            )
        ],
    )
    clamped = FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=0,
        length=12,
        precision=Precision.CLAMPED,
        field_name="WS-T",
    )
    assert smallest_covering(clamped, index_of(asg)) == "REC-T"
    assert "WS-T" in covering_fields(clamped, index_of(asg))
