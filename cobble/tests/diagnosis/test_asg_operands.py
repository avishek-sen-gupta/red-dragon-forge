from cobble.diagnosis.asg_operands import OperandShapes, operand_shapes


def _asg(*statements: dict) -> dict:
    return {
        "program_id": "PROG-A",
        "data_fields": [],
        "linkage_fields": [],
        "paragraphs": [{"name": "PARA-A", "statements": list(statements)}],
    }


def test_a_bare_operand_counts_as_bare():
    asg = _asg({"type": "MOVE", "operands": [{"name": "FLD-A"}, {"name": "FLD-B"}]})
    assert operand_shapes(asg) == OperandShapes(
        bare=2, subscripted=0, ref_modified=0, total=2
    )


def test_a_structured_subscript_counts_as_subscripted():
    asg = _asg(
        {
            "type": "MOVE",
            "operands": [
                {"name": "TBL-ROW", "subscripts": [{"kind": "ref", "name": "IDX-A"}]},
                {"name": "FLD-B"},
            ],
        }
    )
    assert operand_shapes(asg) == OperandShapes(
        bare=1, subscripted=1, ref_modified=0, total=2
    )


def test_reference_modification_counts_separately():
    asg = _asg(
        {
            "type": "MOVE",
            "operands": [
                {
                    "name": "FLD-A",
                    "ref_mod_start": {"kind": "lit", "value": "2"},
                    "ref_mod_length": {"kind": "lit", "value": "3"},
                },
                {"name": "FLD-B"},
            ],
        }
    )
    assert operand_shapes(asg) == OperandShapes(
        bare=1, subscripted=0, ref_modified=1, total=2
    )


def test_an_operand_with_both_counts_in_both():
    asg = _asg(
        {
            "type": "MOVE",
            "operands": [
                {
                    "name": "TBL-ROW",
                    "subscripts": [{"kind": "ref", "name": "IDX-A"}],
                    "ref_mod_start": {"kind": "lit", "value": "1"},
                    "ref_mod_length": {"kind": "lit", "value": "2"},
                }
            ],
        }
    )
    assert operand_shapes(asg) == OperandShapes(
        bare=0, subscripted=1, ref_modified=1, total=1
    )


def test_a_program_with_no_paragraphs_is_not_an_error():
    assert operand_shapes({"program_id": "PROG-A"}) == OperandShapes(
        bare=0, subscripted=0, ref_modified=0, total=0
    )


def test_only_move_operands_are_counted():
    asg = _asg(
        {"type": "MOVE", "operands": [{"name": "FLD-A"}]},
        {"type": "EXEC_CICS", "verb": "READ", "options": {"FILE": {"text": "DS-M"}}},
    )
    assert operand_shapes(asg).total == 1


def test_nested_move_in_if_else_children_is_counted():
    """Regression test for depth-agnostic walk (Override 1).

    The brief's one-level walk would miss this MOVE nested inside
    an IF's else_children inside another IF's children.
    """
    asg = {
        "program_id": "PROG-A",
        "paragraphs": [
            {
                "name": "PARA-A",
                "statements": [
                    {
                        "type": "IF",
                        "condition": {
                            "kind": "simple",
                            "left": "A",
                            "op": "=",
                            "right": "1",
                        },
                        "children": [
                            {
                                "type": "IF",
                                "condition": {
                                    "kind": "simple",
                                    "left": "B",
                                    "op": "=",
                                    "right": "2",
                                },
                                "children": [],
                                "else_children": [
                                    {
                                        "type": "MOVE",
                                        "operands": [
                                            {"name": "FLD-C"},
                                            {"name": "FLD-D"},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    assert operand_shapes(asg) == OperandShapes(
        bare=2, subscripted=0, ref_modified=0, total=2
    )


def test_sections_are_walked():
    """Programs may have top-level sections, each with paragraphs."""
    asg = {
        "program_id": "PROG-A",
        "sections": [
            {
                "name": "SEC-A",
                "paragraphs": [
                    {
                        "name": "PARA-A",
                        "statements": [
                            {
                                "type": "MOVE",
                                "operands": [{"name": "FLD-A"}, {"name": "FLD-B"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    assert operand_shapes(asg) == OperandShapes(
        bare=2, subscripted=0, ref_modified=0, total=2
    )


def test_top_level_statements_are_walked():
    """Programs may have top-level statements outside any paragraph."""
    asg = {
        "program_id": "PROG-A",
        "statements": [
            {"type": "MOVE", "operands": [{"name": "FLD-A"}, {"name": "FLD-B"}]}
        ],
    }
    assert operand_shapes(asg) == OperandShapes(
        bare=2, subscripted=0, ref_modified=0, total=2
    )
