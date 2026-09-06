import json
from pathlib import Path

from cobble.diagnosis.asg_operands import (
    OperandShapes,
    cache_shapes,
    cli,
    operand_shapes,
)


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


def test_non_move_statement_with_subscripts_is_not_counted():
    """The type == MOVE filter prevents false positives from non-MOVE subscripts.

    The old cache holds 2,440 subscripts keys on ADD and COMPUTE operands but
    zero subscripted MOVE operands. An unfiltered diagnostic would pass its own
    gate on a cache that fails the real precondition.
    """
    asg = _asg(
        {
            "type": "ADD",
            "operands": [
                {"name": "TBL-ROW", "subscripts": [{"kind": "ref", "name": "IDX-A"}]},
                {"name": "FLD-B"},
            ],
        }
    )
    assert operand_shapes(asg).subscripted == 0
    assert operand_shapes(asg).total == 0


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


def test_cache_shapes_guards_against_malformed_json(tmp_path: Path, caplog):
    """One malformed file should not crash the diagnostic.

    Good files are still counted, unreadable count tracks bad ones. The
    filename must not appear in logs (channel discipline).
    """
    good_asg = _asg(
        {"type": "MOVE", "operands": [{"name": "FLD-A"}, {"name": "FLD-B"}]}
    )
    (tmp_path / "good.json").write_text(json.dumps(good_asg), encoding="utf-8")
    (tmp_path / "bad-corpus-identifier.json").write_text(
        "{ invalid json", encoding="utf-8"
    )

    shapes = cache_shapes(tmp_path)

    assert shapes.bare == 2
    assert shapes.total == 2
    assert shapes.unreadable == 1
    assert "bad-corpus-identifier" not in caplog.text


def test_cli_exits_three_when_files_unreadable(tmp_path: Path):
    """CLI exits 3 when unreadable files present, even with subscripted MOVEs."""
    good_asg = _asg(
        {
            "type": "MOVE",
            "operands": [
                {"name": "TBL-ROW", "subscripts": [{"kind": "ref", "name": "IDX-A"}]},
            ],
        }
    )
    (tmp_path / "good.json").write_text(json.dumps(good_asg), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{ invalid json", encoding="utf-8")

    exit_code = cli([str(tmp_path)])

    assert exit_code == 3
