"""CFG node id back to the ASG statement it lowered.

srccfg's Node carries operand *names*; subscripts and reference modification
never reach it. fields/ needs the statement, and the node id is already its
address: desugar builds it from the paragraph plus a dotted nesting path.
"""

from __future__ import annotations

from cobol_asg.cobol_statements import CobolStatementType, MoveStatement

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.statements import statement_index


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _moved_into(statement: CobolStatementType) -> str:
    assert isinstance(statement, MoveStatement)
    return statement.targets[0].name


def _when(*children: dict) -> dict:
    return {"type": "WHEN", "condition": "1", "children": list(children)}


def test_a_top_level_statement_is_indexed_at_its_position(program_of):
    asg = program_of([_move("WS-A", "WS-B"), _move("WS-C", "WS-D")])
    index = statement_index(asg)
    second = index["MAIN/1"]
    assert isinstance(second, MoveStatement)
    assert second.targets[0].name == "WS-D"


def test_a_statement_under_an_if_arm_is_indexed_at_the_arm_path(program_of):
    asg = program_of(
        [
            {
                "type": "IF",
                "condition": {"kind": "lit", "value": "1"},
                "children": [_move("WS-A", "WS-B")],
                "else_children": [_move("WS-C", "WS-D")],
            }
        ]
    )
    index = statement_index(asg)
    assert _moved_into(index["MAIN/0.then.0"]) == "WS-B"
    assert _moved_into(index["MAIN/0.else.0"]) == "WS-D"


def test_an_inline_perform_body_is_indexed_under_body_not_then(program_of):
    """``children`` means '.then' for IF and '.body' for an inline PERFORM.

    One segment per attribute cannot say both. It gets the loop wrong, and the
    body drops out of the index in silence. See desugar._perform_body.
    """
    asg = program_of([{"type": "PERFORM", "children": [_move("WS-A", "WS-B")]}])
    index = statement_index(asg)
    assert _moved_into(index["MAIN/0.body.0"]) == "WS-B"
    assert "MAIN/0.then.0" not in index


def test_a_perform_with_a_target_has_no_body_entries(program_of):
    """It lowers to a CALL node, so its children -- if any -- are not a body."""
    asg = program_of([{"type": "PERFORM", "operands": ["OTHER-PARA"]}])
    assert set(statement_index(asg)) == {"MAIN/0"}


def test_an_evaluate_when_body_is_indexed_under_its_branch_position(program_of):
    """EVALUATE keeps its WHENs in ``children``, and the branch segment carries
    the position: desugar._evaluate lowers branch N at '.when.N'."""
    asg = program_of(
        [
            {
                "type": "EVALUATE",
                "subject": "WS-K",
                "children": [
                    _when(_move("WS-A", "WS-B")),
                    {"type": "WHEN_OTHER", "children": [_move("WS-C", "WS-D")]},
                ],
            }
        ]
    )
    index = statement_index(asg)
    assert _moved_into(index["MAIN/0.when.0.0"]) == "WS-B"
    assert _moved_into(index["MAIN/0.when.1.0"]) == "WS-D"


def test_a_search_indexes_both_its_whens_and_its_at_end(program_of):
    asg = program_of(
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [{"condition": "1", "children": [_move("WS-A", "WS-B")]}],
                "at_end": [_move("WS-C", "WS-D")],
            }
        ]
    )
    index = statement_index(asg)
    assert _moved_into(index["MAIN/0.when.0.0"]) == "WS-B"
    assert _moved_into(index["MAIN/0.at_end.0"]) == "WS-D"


def test_division_level_statements_are_indexed_under_the_synthetic_paragraph(
    asg_of,
):
    """Statements belonging to no paragraph still execute, and build.py gives
    them a synthetic name -- so keying off asg.paragraphs alone misses them."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "statements": [_move("WS-A", "WS-B")],
            "paragraphs": [{"name": "MAIN", "statements": [_move("WS-C", "WS-D")]}],
        }
    )
    index = statement_index(asg)
    assert _moved_into(index["%MAIN/0"]) == "WS-B"
    assert _moved_into(index["MAIN/0"]) == "WS-D"


def test_a_duplicate_paragraph_name_is_indexed_under_its_renamed_form(asg_of):
    """Legal across sections, but the CFG renames later occurrences to keep node
    ids unique. Indexing by the raw ASG name collapses both onto one key."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "sections": [
                {
                    "name": "S-A",
                    "paragraphs": [
                        {"name": "DUP", "statements": [_move("WS-A", "WS-B")]}
                    ],
                },
                {
                    "name": "S-B",
                    "paragraphs": [
                        {"name": "DUP", "statements": [_move("WS-C", "WS-D")]}
                    ],
                },
            ],
        }
    )
    index = statement_index(asg)
    assert _moved_into(index["DUP/0"]) == "WS-B"
    assert _moved_into(index["DUP%2/0"]) == "WS-D"


def test_every_statement_bearing_cfg_node_has_an_entry(asg_of):
    """The convention lives in desugar; this is the guard against drift.

    A node id with no '#' addresses a statement. If desugar changes how it
    builds a path and this module does not, that id stops resolving -- and
    every extent for that statement silently disappears rather than failing.

    Every nesting shape desugar dispatches on is present below, because a shape
    the fixture omits is one this guard cannot see: the EVALUATE, inline
    PERFORM, and SEARCH arms each lower under a segment the others do not.
    """
    asg = asg_of(
        {
            "program_id": "PROGA",
            "statements": [_move("WS-X", "WS-Y")],
            "sections": [
                {
                    "name": "S-A",
                    "statements": [_move("WS-P", "WS-Q")],
                    "paragraphs": [
                        {
                            "name": "DUP",
                            "statements": [
                                {
                                    "type": "SEARCH",
                                    "table": "WS-TABLE",
                                    "whens": [
                                        {
                                            "condition": "1",
                                            "children": [_move("WS-E", "WS-F")],
                                        }
                                    ],
                                    "at_end": [_move("WS-G", "WS-H")],
                                }
                            ],
                        }
                    ],
                }
            ],
            "paragraphs": [
                {
                    "name": "DUP",
                    "statements": [
                        {
                            "type": "IF",
                            "condition": {"kind": "lit", "value": "1"},
                            "children": [
                                {
                                    "type": "EVALUATE",
                                    "subject": "WS-K",
                                    "children": [
                                        _when(
                                            {
                                                "type": "PERFORM",
                                                "children": [_move("WS-A", "WS-B")],
                                            }
                                        ),
                                        {
                                            "type": "WHEN_OTHER",
                                            "children": [_move("WS-I", "WS-J")],
                                        },
                                    ],
                                }
                            ],
                            "else_children": [_move("WS-C", "WS-D")],
                        },
                        {
                            "type": "CALL",
                            "program": "'PROGB'",
                            "using": [],
                            "on_exception": [_move("WS-L", "WS-M")],
                            "not_on_exception": [_move("WS-N", "WS-O")],
                        },
                        {
                            "type": "STRING",
                            "sendings": [],
                            "into": {"name": "WS-S"},
                            "on_overflow": [_move("WS-T", "WS-U")],
                            "not_on_overflow": [_move("WS-V", "WS-W")],
                        },
                    ],
                }
            ],
        }
    )
    cfg = build_program(asg)
    index = statement_index(asg)
    unsuffixed = {
        node.id
        for node in cfg.nodes
        if "#" not in node.id and (node.writes or node.reads)
    }
    assert unsuffixed
    assert unsuffixed <= set(index)
