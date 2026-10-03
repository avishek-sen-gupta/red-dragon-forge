"""EXIT PARAGRAPH and EXIT SECTION: a jump to the end of what they leave.

The end is where the fall-through to the next paragraph and the RETURN of every
PERFORM already hang, so one edge there gives both: a PERFORM of the paragraph comes
back, and a paragraph that is run into falls out of it as it would off its last
statement. The rest of the paragraph -- or section -- loses that route in.

The other EXITs must not move. Plain EXIT is the PERFORM THRU sentinel, and EXIT
PERFORM [CYCLE] outside any inline PERFORM -- which no compiler accepts -- has nothing
to leave, so it falls through rather than jump to a node that does not exist.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.build import build_program, end_id
from cobble.dataflow.srccfg.cfg import Edge, EdgeKind
from cobble.dataflow.srccfg.dataflow import guards_of, reaching_conditions


def _exit(kind: str) -> dict:
    return {"type": "EXIT", "kind": kind} if kind else {"type": "EXIT"}


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def test_exit_paragraph_jumps_to_its_paragraphs_end(program_of) -> None:
    cfg = build_program(program_of([_exit("paragraph"), _move("'A'", "WS-AFTER")]))

    assert cfg.successors("MAIN/0") == (
        Edge(source="MAIN/0", target=end_id("MAIN"), kind=EdgeKind.GOTO),
    )
    assert cfg.predecessors("MAIN/1") == ()


def test_exit_section_jumps_past_the_sections_later_paragraphs(asg_of) -> None:
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "sections": [
                    {
                        "name": "WORK",
                        "paragraphs": [
                            {
                                "name": "W1",
                                "statements": [
                                    _exit("section"),
                                    _move("'A'", "WS-W1"),
                                ],
                            },
                            {"name": "W2", "statements": [_move("'B'", "WS-W2")]},
                        ],
                    }
                ],
            }
        )
    )

    assert cfg.successors("W1/0") == (
        Edge(source="W1/0", target=end_id("WORK"), kind=EdgeKind.GOTO),
    )
    assert cfg.predecessors("W1/1") == ()
    assert guards_of(reaching_conditions(cfg), "W2/0") == ()


def test_the_other_exits_fall_through(program_of) -> None:
    cfg = build_program(
        program_of(
            [
                _exit(""),
                _exit("perform"),
                _exit("perform-cycle"),
                _move("'A'", "WS-AFTER"),
            ]
        )
    )

    assert [cfg.successors(node) for node in ("MAIN/0", "MAIN/1", "MAIN/2")] == [
        (Edge(source="MAIN/0", target="MAIN/1", kind=EdgeKind.FLOW),),
        (Edge(source="MAIN/1", target="MAIN/2", kind=EdgeKind.FLOW),),
        (Edge(source="MAIN/2", target="MAIN/3", kind=EdgeKind.FLOW),),
    ]
