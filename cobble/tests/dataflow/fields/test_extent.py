"""One case per operand form, asserting precision on each.

The asymmetry under test: only an EXACT extent may later kill a definition, so a
computed subscript must never produce one, and reference modification inside a
computed subscript must not pretend to know which occurrence it sliced.
"""

from __future__ import annotations

from cobble.dataflow.fields.extent import NO_EXTENT_REASONS, operand_extents
from cobol_asg.cobol_expression import FieldRefNode, LiteralNode
from cobol_asg.ref_mod import (
    FunctionCallOperand,
    RefModBinOp,
    RefModLengthOf,
    RefModLiteral,
    RefModOperand,
    RefModReference,
)
from cobol_memory.field_extent import Precision
from cobol_memory.region_id import RegionId


def _literals(*values: str) -> tuple[LiteralNode, ...]:
    return tuple(LiteralNode(value=value) for value in values)


def _references(*names: str) -> tuple[FieldRefNode, ...]:
    return tuple(FieldRefNode(name=name) for name in names)


def _ref_mod(name: str, start: str, length: str = "", **extra) -> RefModOperand:
    return RefModOperand(
        name=name,
        ref_mod_start=RefModLiteral(value=start),
        ref_mod_length=RefModLiteral(value=length) if length else None,
        **extra,
    )


def _one(program_of, fields: list[dict], **section):
    return program_of([], **(section if section else {"data_fields": fields}))


def _bytes(extent) -> tuple[int, int]:
    return (extent.start, extent.length)


def test_a_bare_elementary_name_is_one_exact_extent(program_of, index_of, field):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="WS-A"), index_of(asg))
    (extent,) = result.extents
    assert _bytes(extent) == (0, 10)
    assert extent.precision is Precision.EXACT
    assert extent.region is RegionId.WORKING_STORAGE


def test_a_group_name_spans_its_children(program_of, index_of, field):
    asg = _one(
        program_of,
        [
            field(
                1,
                "REC-A",
                children=[
                    field(5, "WS-A", "X(10)", offset=0),
                    field(5, "WS-B", "X(6)", offset=10),
                ],
            )
        ],
    )
    (extent,) = operand_extents(RefModOperand(name="REC-A"), index_of(asg)).extents
    assert _bytes(extent) == (0, 16)


def test_a_literal_subscript_selects_one_occurrence_exactly(
    program_of, index_of, field
):
    asg = _one(
        program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(4)", occurs=5)])]
    )
    operand = RefModOperand(name="WS-A", subscripts=_literals("3"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (8, 4)
    assert extent.precision is Precision.EXACT


def test_a_computed_subscript_clamps_to_the_whole_table(program_of, index_of, field):
    asg = _one(program_of, [_table_and_index(field)])
    operand = RefModOperand(name="WS-A", subscripts=_references("WS-I"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (0, 20)
    assert extent.precision is Precision.CLAMPED


def test_a_constant_reference_modification_narrows_and_stays_exact(
    program_of, index_of, field
):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    operand = _ref_mod("WS-A", start="3", length="4")
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (2, 4)
    assert extent.precision is Precision.EXACT


def test_reference_modification_with_no_length_runs_to_the_end(
    program_of, index_of, field
):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    (extent,) = operand_extents(_ref_mod("WS-A", start="4"), index_of(asg)).extents
    assert _bytes(extent) == (3, 7)


def test_an_arithmetic_reference_modification_start_still_folds(
    program_of, index_of, field
):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    operand = RefModOperand(
        name="WS-A",
        ref_mod_start=RefModBinOp(
            op="+", left=RefModLiteral(value="2"), right=RefModLiteral(value="1")
        ),
        ref_mod_length=RefModLiteral(value="2"),
    )
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (2, 2)
    assert extent.precision is Precision.EXACT


def test_length_of_in_a_reference_modification_folds_to_the_named_length(
    program_of, index_of, field
):
    asg = _one(
        program_of,
        [
            field(
                1,
                "REC-A",
                children=[
                    field(5, "WS-HEAD", "X(3)"),
                    field(5, "WS-A", "X(10)", offset=3),
                ],
            )
        ],
    )
    operand = RefModOperand(
        name="WS-A",
        ref_mod_start=RefModBinOp(
            op="+", left=RefModLengthOf(name="WS-HEAD"), right=RefModLiteral(value="1")
        ),
        ref_mod_length=RefModLengthOf(name="WS-HEAD"),
    )
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert (_bytes(extent), extent.precision) == ((6, 3), Precision.EXACT)


def test_a_computed_reference_modification_clamps_to_the_whole_field(
    program_of, index_of, field
):
    asg = _one(
        program_of,
        [
            field(
                1,
                "REC-A",
                children=[
                    field(5, "WS-A", "X(10)", offset=0),
                    field(5, "WS-I", "9(4)", offset=10),
                ],
            )
        ],
    )
    operand = RefModOperand(name="WS-A", ref_mod_start=RefModReference(name="WS-I"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (0, 10)
    assert extent.precision is Precision.CLAMPED


def test_reference_modification_never_narrows_a_computed_subscript(
    program_of, index_of, field
):
    """A weak update stays weak: the slice could land in any of the five rows."""
    asg = _one(program_of, [_table_and_index(field)])
    operand = _ref_mod("WS-A", start="2", length="1", subscripts=_references("WS-I"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (0, 20)
    assert extent.precision is Precision.CLAMPED


def test_a_multidimensional_literal_subscript_selects_one_cell(
    program_of, index_of, field
):
    asg = _one(
        program_of,
        [
            field(
                1,
                "REC-A",
                children=[
                    field(
                        5,
                        "WS-ROW",
                        occurs=3,
                        children=[field(10, "WS-COL", "X(2)", occurs=4)],
                    )
                ],
            )
        ],
    )
    operand = RefModOperand(name="WS-COL", subscripts=_literals("2", "3"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (12, 2)
    assert extent.precision is Precision.EXACT


def test_a_subscript_past_the_declared_occurs_clamps_rather_than_vanishing(
    program_of, index_of, field
):
    """Answering "no extent" for an out-of-range literal would drop a real edge."""
    asg = _one(program_of, [_table_and_index(field)])
    operand = RefModOperand(name="WS-A", subscripts=_literals("9"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert _bytes(extent) == (0, 20)
    assert extent.precision is Precision.CLAMPED


def test_a_table_name_without_subscripts_matches_no_cell(program_of, index_of, field):
    asg = _one(
        program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(4)", occurs=5)])]
    )
    result = operand_extents(RefModOperand(name="WS-A"), index_of(asg))
    assert result.extents == ()
    assert result.reason == "unknown-name"


def test_length_of_yields_no_extent_and_says_why(program_of, index_of, field):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="", length_of="WS-A"), index_of(asg))
    assert result.extents == ()
    assert result.reason == "length-of"


def test_a_function_call_operand_yields_no_extent_and_says_why(
    program_of, index_of, field
):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(FunctionCallOperand(name="UPPER-CASE"), index_of(asg))
    assert result.extents == ()
    assert result.reason == "function"


def test_an_unknown_name_yields_no_extent_and_says_why(program_of, index_of, field):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="WS-NOPE"), index_of(asg))
    assert result.extents == ()
    assert result.reason == "unknown-name"


def test_a_figurative_constant_is_not_reported_as_an_unknown_name(
    program_of, index_of, field
):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="SPACES"), index_of(asg))
    assert result.extents == ()
    assert result.reason == "figurative"


def test_every_no_extent_reason_this_module_can_produce_is_declared():
    assert NO_EXTENT_REASONS == frozenset(
        {"unknown-name", "length-of", "function", "figurative"}
    )


def test_a_qualifier_disambiguates_a_name_declared_twice(program_of, index_of, field):
    asg = _one(program_of, _two_records_named_alike(field))
    unqualified = operand_extents(RefModOperand(name="WS-N"), index_of(asg))
    assert len(unqualified.extents) == 2
    qualified = operand_extents(
        RefModOperand(name="WS-N", qualifiers=("REC-B",)), index_of(asg)
    )
    assert len(qualified.extents) == 1


def test_a_reference_is_case_insensitive_the_way_cobol_is(program_of, index_of, field):
    asg = _one(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    (extent,) = operand_extents(RefModOperand(name="ws-a"), index_of(asg)).extents
    assert _bytes(extent) == (0, 10)


def test_a_linkage_record_lands_in_the_linkage_region(program_of, index_of, field):
    asg = _one(
        program_of,
        [],
        linkage_fields=[field(1, "REC-L", children=[field(5, "WS-L", "X(4)")])],
    )
    (extent,) = operand_extents(RefModOperand(name="WS-L"), index_of(asg)).extents
    assert extent.region is RegionId.LINKAGE


def test_two_records_in_one_region_do_not_share_an_address(program_of, index_of, field):
    """Each record starts at 0 in layout, so extents must re-address them.

    Otherwise REC-B's first four bytes must_cover REC-A's, and a write through
    one name silently kills a live definition made through the other.
    """
    index = index_of(_one(program_of, _two_records_named_alike(field)))
    first, second = operand_extents(RefModOperand(name="WS-N"), index).extents
    assert (_bytes(first), _bytes(second)) == ((0, 4), (4, 4))
    assert not first.may_alias(second)
    assert not second.must_cover(first)


def test_a_clamped_extent_covers_nothing_even_when_it_contains_it(
    program_of, index_of, field
):
    index = index_of(_one(program_of, [_table_and_index(field)]))
    (whole,) = operand_extents(
        RefModOperand(name="WS-A", subscripts=_references("WS-I")), index
    ).extents
    (third,) = operand_extents(
        RefModOperand(name="WS-A", subscripts=_literals("3")), index
    ).extents
    assert whole.may_alias(third)
    assert not whole.must_cover(third)
    assert third.must_cover(third)


def test_a_group_extent_reports_the_elementary_fields_it_covers(
    program_of, index_of, field
):
    index = index_of(_one(program_of, [_two_field_record(field)]))
    (group,) = operand_extents(RefModOperand(name="REC-A"), index).extents
    assert tuple(cell.name for cell in index.elementary_within(group)) == (
        "WS-A",
        "WS-B",
    )


def test_a_member_extent_reports_the_groups_that_contain_it(
    program_of, index_of, field
):
    index = index_of(_one(program_of, [_two_field_record(field)]))
    (member,) = operand_extents(RefModOperand(name="WS-A"), index).extents
    assert tuple(cell.name for cell in index.containing(member)) == ("REC-A", "WS-A")


def _table_and_index(field) -> dict:
    return field(
        1,
        "REC-A",
        children=[
            field(5, "WS-A", "X(4)", occurs=5, offset=0),
            field(5, "WS-I", "9(4)", offset=20),
        ],
    )


def _two_field_record(field) -> dict:
    return field(
        1,
        "REC-A",
        children=[
            field(5, "WS-A", "X(10)", offset=0),
            field(5, "WS-B", "X(6)", offset=10),
        ],
    )


def _two_records_named_alike(field) -> list[dict]:
    return [
        field(1, "REC-A", children=[field(5, "WS-N", "X(4)")]),
        field(1, "REC-B", children=[field(5, "WS-N", "X(4)")]),
    ]
