"""Every CFG node carries the source span of the construct it was lowered from."""

from __future__ import annotations

from collections import Counter

from cobble.dataflow.srccfg.build import build_program

SOURCE = "src/PROGA.cbl"


def _at(line: int) -> dict:
    return {"line_start": line, "col_start": 8, "line_end": line, "col_end": 40}


def _cond(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _move(line: int) -> dict:
    return {
        "type": "MOVE",
        "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}],
        **_at(line),
    }


def _program(asg_of):
    first = [
        {
            "type": "IF",
            "condition": _cond("WS-A", "'Y'"),
            "children": [_move(13)],
            **_at(12),
        },
        {"type": "PERFORM", "operands": ["2000-SECOND"], **_at(14)},
        {
            "type": "PERFORM",
            "perform_type": "TIMES",
            "times": "WS-COUNT",
            "children": [_move(16)],
            **_at(15),
        },
        {
            "type": "PERFORM",
            "perform_type": "VARYING",
            "varying_var": "WS-IDX",
            "varying_from": "1",
            "varying_by": "1",
            "until": _cond("WS-IDX", "10"),
            "children": [_move(18)],
            **_at(17),
        },
        {"type": "CALL", "program": "'PROGB'", "using": [], **_at(19)},
        {
            "type": "GOTO",
            "form": "simple",
            "target": {"paragraph": "2000-SECOND"},
            **_at(20),
        },
    ]
    return asg_of(
        {
            "program_id": "PROGA",
            "sections": [
                {
                    "name": "MAIN-SECTION",
                    "paragraphs": [
                        {"name": "1000-FIRST", "statements": first, **_at(11)}
                    ],
                    **_at(10),
                }
            ],
            "paragraphs": [
                {"name": "2000-SECOND", "statements": [_move(31)], **_at(30)}
            ],
        }
    )


def test_every_node_carries_the_span_of_the_construct_it_came_from(asg_of) -> None:
    cfg = build_program(_program(asg_of), source_file=SOURCE)

    assert Counter((n.kind.value, n.span.line_start) for n in cfg.nodes) == Counter(
        {
            ("LABEL", 10): 1,
            ("NOP", 10): 1,
            ("LABEL", 11): 1,
            ("NOP", 11): 1,
            ("TEST", 12): 1,
            ("ASSIGN", 13): 1,
            ("CALL", 14): 1,
            ("TEST", 15): 1,
            ("ASSIGN", 16): 1,
            ("ASSIGN", 17): 2,
            ("TEST", 17): 1,
            ("ASSIGN", 18): 1,
            ("CALL", 19): 1,
            ("CALL", 20): 1,
            ("LABEL", 30): 1,
            ("NOP", 30): 1,
            ("ASSIGN", 31): 1,
        }
    )
    assert {n.span.source_file for n in cfg.nodes} == {SOURCE}
