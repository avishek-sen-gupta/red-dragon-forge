"""One case per transfer rule in the design, plus the weak-update asymmetry."""

from __future__ import annotations

import pytest
from cobble.dataflow.fields.extent import operand_extents
from cobble.dataflow.fields.state import EMPTY, reaching, values_at
from cobble.dataflow.fields.transfer import transfer
from cobble.dataflow.fields.values import of_value
from cobble.dataflow.srccfg.statements import statement_index
from cobol_asg.cobol_expression import LiteralNode
from cobol_asg.ref_mod import RefModOperand


@pytest.fixture
def names_reaching():
    """Every origin or source field name reaching one named operand."""

    def reaching_at(state, index, name: str, **operand) -> set[str]:
        (extent,) = operand_extents(RefModOperand(name=name, **operand), index).extents
        return {
            source.origin or source.extent.field_name
            for source in reaching(state, extent)
        }

    return reaching_at


@pytest.fixture
def after(index_of):
    """The state after running every statement of a one-paragraph program."""

    def run(asg):
        index = index_of(asg)
        state = EMPTY
        for position, statement in enumerate(asg.paragraphs[0].statements):
            state = transfer(statement, f"MAIN/{position}", state, index)
        return state, index

    return run


def _move(source: str, *targets: str) -> dict:
    return {
        "type": "MOVE",
        "operands": [{"name": source}, *({"name": target} for target in targets)],
    }


def test_an_alphanumeric_move_gives_the_target_the_source(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [_move("WS-A", "WS-B")],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-B") == {"WS-A"}


def test_a_move_distributes_to_every_receiving_field(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [_move("WS-A", "WS-B", "WS-C")],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                    field(5, "WS-C", "X(4)", offset=8),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-B") == {"WS-A"}
    assert names_reaching(state, index, "WS-C") == {"WS-A"}


def test_a_group_move_is_one_write_at_the_group_and_every_child_aliases_into_it(
    program_of, field, after, names_reaching
):
    """The case names cannot express: two copybook layouts over one shape.

    Which of the source's bytes each child took is offset arithmetic over the two
    extents -- byte k from byte k, because a group operand makes the MOVE an
    alphanumeric copy -- so a write per child restated the declared layout once
    per flow. The children still reach the source, by aliasing into the range the
    group write covered; the offsets are the query's to recover.
    """
    asg = program_of(
        [_move("REC-SRC", "REC-DST")],
        data_fields=[
            field(
                1,
                "REC-SRC",
                children=[
                    field(5, "SRC-ONE", "X(4)", offset=0),
                    field(5, "SRC-TWO", "X(6)", offset=4),
                ],
            ),
            field(
                1,
                "REC-DST",
                children=[
                    field(5, "DST-ONE", "X(4)", offset=0),
                    field(5, "DST-TWO", "X(6)", offset=4),
                ],
            ),
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "REC-DST") == {"REC-SRC"}
    assert names_reaching(state, index, "DST-ONE") == {"REC-SRC"}
    assert names_reaching(state, index, "DST-TWO") == {"REC-SRC"}


def test_a_group_move_shorter_than_its_target_still_writes_the_whole_target(
    program_of, field, after, names_reaching
):
    """The tail past the source's end is spaces, and that is not a flow fact.

    A LITERAL SPACES source per padded child was a per-child restatement of one
    subtraction: the target's length less the source's. The write covers the whole
    target because the whole target was written.
    """
    asg = program_of(
        [_move("REC-SRC", "REC-DST")],
        data_fields=[
            field(1, "REC-SRC", children=[field(5, "SRC-ONE", "X(4)", offset=0)]),
            field(
                1,
                "REC-DST",
                children=[
                    field(5, "DST-ONE", "X(4)", offset=0),
                    field(5, "DST-TAIL", "X(6)", offset=4),
                ],
            ),
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "REC-DST") == {"REC-SRC"}
    assert names_reaching(state, index, "DST-TAIL") == {"REC-SRC"}


def test_a_comp_operand_gets_whole_to_whole_with_no_byte_split(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [_move("WS-BIN", "REC-DST")],
        data_fields=[
            field(
                1,
                "REC-SRC",
                children=[field(5, "WS-BIN", "9(8)", offset=0, usage="COMP")],
            ),
            field(
                1,
                "REC-DST",
                children=[
                    field(5, "DST-ONE", "X(2)", offset=0),
                    field(5, "DST-TWO", "X(2)", offset=2),
                ],
            ),
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "REC-DST") == {"WS-BIN"}
    assert names_reaching(state, index, "DST-ONE") == {"WS-BIN"}


def test_a_figurative_constant_source_reaches_the_target_as_a_literal(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [_move("SPACES", "WS-A")],
        data_fields=[field(1, "REC", children=[field(5, "WS-A", "X(4)", offset=0)])],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-A") == {"LITERAL"}


def test_a_computed_subscript_target_is_a_weak_update(
    program_of, field, after, names_reaching
):
    """A CLAMPED write adds provenance without removing occurrence 1's."""
    asg = program_of(
        [
            {
                "type": "MOVE",
                "operands": [
                    {"name": "WS-A"},
                    {"name": "WS-T", "subscripts": [{"kind": "lit", "value": "1"}]},
                ],
            },
            {
                "type": "MOVE",
                "operands": [
                    {"name": "WS-B"},
                    {"name": "WS-T", "subscripts": [{"kind": "ref", "name": "WS-I"}]},
                ],
            },
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                    field(5, "WS-T", "X(4)", offset=8, occurs=3),
                    field(5, "WS-I", "9(4)", offset=20),
                ],
            )
        ],
    )
    state, index = after(asg)
    reached = names_reaching(state, index, "WS-T", subscripts=(LiteralNode(value="1"),))
    assert reached == {"WS-A", "WS-B"}


def test_initialize_gives_every_member_a_literal(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [{"type": "INITIALIZE", "operands": ["REC"]}],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-A") == {"LITERAL"}
    assert names_reaching(state, index, "WS-B") == {"LITERAL"}


def test_add_gives_the_target_the_union_of_its_operands(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "ADD",
                "operands": [{"name": "WS-A"}],
                "targets": [{"name": "WS-B"}],
            }
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "9(4)", offset=0),
                    field(5, "WS-B", "9(4)", offset=4),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-B") == {"WS-A", "WS-B"}


def test_add_giving_writes_the_giving_target_not_the_second_operand(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "ADD",
                "operands": [{"name": "WS-A"}, {"name": "WS-B"}],
                "giving": [{"name": "WS-C"}],
            }
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "9(4)", offset=0),
                    field(5, "WS-B", "9(4)", offset=4),
                    field(5, "WS-C", "9(4)", offset=8),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-C") == {"WS-A", "WS-B"}
    assert names_reaching(state, index, "WS-B") == set()


def test_compute_reads_every_field_in_its_expression(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "COMPUTE",
                "expression": {
                    "kind": "binop",
                    "op": "+",
                    "left": {"kind": "ref", "name": "WS-A"},
                    "right": {"kind": "ref", "name": "WS-B"},
                },
                "targets": [{"name": "WS-C"}],
            }
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "9(4)", offset=0),
                    field(5, "WS-B", "9(4)", offset=4),
                    field(5, "WS-C", "9(4)", offset=8),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-C") == {"WS-A", "WS-B"}


def test_string_gives_the_into_target_every_sending_operand(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "STRING",
                "sendings": [
                    {"value": {"name": "WS-A"}, "delimited_by": "SIZE"},
                    {"value": {"name": "WS-B"}, "delimited_by": "SIZE"},
                ],
                "into": {"name": "WS-OUT"},
            }
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                    field(5, "WS-OUT", "X(8)", offset=8),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-OUT") == {"WS-A", "WS-B"}


def test_read_into_marks_the_target_as_coming_from_the_file(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [{"type": "READ", "file_name": "CUSTFILE", "into": "WS-REC"}],
        data_fields=[field(1, "REC", children=[field(5, "WS-REC", "X(8)", offset=0)])],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-REC") == {"FILE:CUSTFILE"}


def test_call_using_by_reference_marks_the_argument_as_written_by_the_callee(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "CALL",
                "program": "SUBPROG",
                "using": [
                    {"name": "WS-A", "type": "REFERENCE"},
                    {"name": "WS-B", "type": "CONTENT"},
                ],
            }
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                ],
            )
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-A") == {"%CALL:SUBPROG"}
    assert names_reaching(state, index, "WS-B") == set()


def test_a_call_through_a_data_item_credits_a_sink_no_member_can_be(
    program_of, field, after, names_reaching
):
    """CALL WS-PROG writes the argument as surely as CALL 'SUBPROG' does, so the
    write stays. Only the sink changes: ``%CALL:WS-PROG`` would be joined to a member
    of that name, while the marked form keeps the field for a follow-up query and
    can never be mistaken for one."""
    asg = program_of(
        [
            {
                "type": "CALL",
                "program_ref": {"name": "WS-PROG"},
                "using": [{"name": "WS-A", "type": "REFERENCE"}],
            }
        ],
        data_fields=[
            field(1, "REC", children=[field(5, "WS-A", "X(4)", offset=0)]),
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-A") == {"%CALL:%DYNAMIC:WS-PROG"}


def test_exec_cics_read_into_marks_the_target_as_coming_from_the_file(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "EXEC_CICS",
                "verb": "READ",
                "options": {
                    "FILE": {"text": "CUSTFILE", "is_literal": True},
                    "INTO": {"text": "WS-REC", "is_literal": False},
                },
            }
        ],
        data_fields=[field(1, "REC", children=[field(5, "WS-REC", "X(8)", offset=0)])],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-REC") == {"FILE:CUSTFILE"}


def test_exec_cics_receive_map_marks_the_target_as_cics_state(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "EXEC_CICS",
                "verb": "RECEIVE",
                "options": {
                    "MAP": {"text": "'MAPA'", "is_literal": True},
                    "INTO": {"text": "WS-MAP", "is_literal": False},
                },
            }
        ],
        data_fields=[field(1, "REC", children=[field(5, "WS-MAP", "X(8)", offset=0)])],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-MAP") == {"%CICS-STATE"}


def test_exec_cics_link_marks_the_commarea_as_written_by_the_callee(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "EXEC_CICS",
                "verb": "LINK",
                "options": {
                    "PROGRAM": {"text": "'SUBPROG'", "is_literal": True},
                    "COMMAREA": {"text": "WS-COMM", "is_literal": False},
                },
            }
        ],
        data_fields=[field(1, "REC", children=[field(5, "WS-COMM", "X(8)", offset=0)])],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-COMM") == {"%CALL:'SUBPROG'"}


def test_an_unhandled_statement_leaves_the_state_untouched(program_of, field, after):
    asg = program_of(
        [{"type": "DISPLAY", "operands": ["WS-A"]}],
        data_fields=[field(1, "REC", children=[field(5, "WS-A", "X(4)", offset=0)])],
    )
    state, _ = after(asg)
    assert state == EMPTY


def test_compute_with_stub_source_tags_it_by_name(
    program_of, field, after, names_reaching
):
    """A COMPUTE source with no declared layout (stub copybook) yields FIELD:<name>
    so backward provenance is not opaque.  WS-PRICE is declared; EXTERN-PRICE is not."""
    asg = program_of(
        [
            {
                "type": "COMPUTE",
                "expression": {"kind": "ref", "name": "EXTERN-PRICE"},
                "targets": [{"name": "WS-PRICE"}],
            }
        ],
        data_fields=[
            field(1, "REC", children=[field(5, "WS-PRICE", "9(8)", offset=0)])
        ],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-PRICE") == {"FIELD:EXTERN-PRICE"}


def test_compute_with_mixed_sources_includes_stub_names(
    program_of, field, after, names_reaching
):
    """When some COMPUTE operands resolve and some don't, both are recorded."""
    asg = program_of(
        [
            {
                "type": "COMPUTE",
                "expression": {
                    "kind": "binop",
                    "op": "+",
                    "left": {"kind": "ref", "name": "WS-A"},
                    "right": {"kind": "ref", "name": "EXTERN-DISCOUNT"},
                },
                "targets": [{"name": "WS-PRICE"}],
            }
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "9(4)", offset=0),
                    field(5, "WS-PRICE", "9(4)", offset=4),
                ],
            )
        ],
    )
    state, index = after(asg)
    result = names_reaching(state, index, "WS-PRICE")
    assert "WS-A" in result
    assert "FIELD:EXTERN-DISCOUNT" in result


def test_a_subscripted_cics_commarea_is_written_at_its_own_occurrence(
    program_of, field, after, names_reaching
):
    """LINK COMMAREA(WS-COMMS(2)) hands the callee one entry of a table. Read as the
    bare name it resolves at arity 0 against a field declared OCCURS, matches no
    cell, and the write lands nowhere at all (forge-zgn)."""
    asg = program_of(
        [
            {
                "type": "EXEC_CICS",
                "verb": "LINK",
                "options": {
                    "PROGRAM": {"text": "'SUBPROG'", "is_literal": True},
                    "COMMAREA": {
                        "text": "WS-COMMS",
                        "is_literal": False,
                        "subscripts": [{"kind": "lit", "value": "2"}],
                    },
                },
            }
        ],
        data_fields=[
            field(1, "REC", children=[field(5, "WS-COMMS", "X(8)", offset=0, occurs=3)])
        ],
    )
    state, index = after(asg)
    reached = names_reaching(
        state, index, "WS-COMMS", subscripts=(LiteralNode(value="2"),)
    )
    assert reached == {"%CALL:'SUBPROG'"}


def test_an_unsubscripted_cics_commarea_is_written_exactly_as_before(
    program_of, field, after, names_reaching
):
    asg = program_of(
        [
            {
                "type": "EXEC_CICS",
                "verb": "LINK",
                "options": {
                    "PROGRAM": {"text": "'SUBPROG'", "is_literal": True},
                    "COMMAREA": {"text": "WS-COMM", "is_literal": False},
                },
            }
        ],
        data_fields=[field(1, "REC", children=[field(5, "WS-COMM", "X(8)", offset=0)])],
    )
    state, index = after(asg)
    assert names_reaching(state, index, "WS-COMM") == {"%CALL:'SUBPROG'"}


def test_a_literal_move_carries_its_text_fitted_to_the_target(
    index_of, program_of, field
):
    asg = program_of(
        [],
        paragraphs=[
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "MOVE",
                        "operands": [{"name": "'COSGN00C'"}, {"name": "WS-PGM"}],
                    }
                ],
            }
        ],
        data_fields=[field(1, "WS-PGM", "X(8)")],
    )
    index = index_of(asg)
    statement = statement_index(asg)[next(iter(statement_index(asg)))]
    after = transfer(statement, "n1", EMPTY, index)
    target = index.extent_of(index.cells_named("WS-PGM", (), 0)[0])

    assert values_at(after, target) == of_value(b"COSGN00C")
