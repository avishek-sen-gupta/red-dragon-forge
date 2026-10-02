"""Reachability from one PERFORM: what can run until control returns, and how else
the PERFORM can end -- over CFGs built the way cobble-srccfg-build builds them."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import pytest
from cobble.dataflow.srccfg.cfg import EdgeKind
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.reach.reach_error import ReachError
from cobble.dataflow.srccfg.reach.walk import reach_rows
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow
from cobble.dataflow.srccfg.rows.refused_row import CfgRefusedRow
from cobble.dataflow.srccfg.rows.summary_row import CfgSummaryRow
from cobble.dataflow.srccfg.rows.unresolved_row import CfgUnresolvedRow
from cobol_asg.asg_types import CobolASG

Asg = Callable[[Mapping], CobolASG]


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _perform(target: str, thru: str = "") -> dict:
    return {"type": "PERFORM", "operands": [target], **({"thru": thru} if thru else {})}


def _goto(target: str) -> dict:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


def _cics(verb: str, options: Mapping) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": dict(options)}


def _if(then: dict, otherwise: dict) -> dict:
    return {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {
                "left": {"kind": "ref", "name": "WS-F"},
                "op": "==",
                "right": {"kind": "lit", "value": "'Y'"},
            },
        },
        "children": [then],
        "else_children": [otherwise],
    }


def _para(name: str, *statements: dict) -> dict:
    return {"name": name, "statements": list(statements)}


def _rows(asg_of: Asg, seed: str, *paragraphs: dict) -> tuple[CfgRow, ...]:
    cfg = program_cfg(asg_of({"program_id": "PROGA", "paragraphs": list(paragraphs)}))
    return tuple(reach_rows(cfg, seed))


def _nodes(rows: Sequence[CfgRow]) -> list[str]:
    return [row.id for row in rows if isinstance(row, CfgNodeRow)]


def _paragraphs(rows: Sequence[CfgRow]) -> list[str]:
    return list(
        dict.fromkeys(row.paragraph for row in rows if isinstance(row, CfgNodeRow))
    )


def _edges(rows: Sequence[CfgRow]) -> set[tuple[str, str, EdgeKind]]:
    return {
        (row.source, row.target, row.kind)
        for row in rows
        if isinstance(row, CfgEdgeRow)
    }


def _outcomes(rows: Sequence[CfgRow]) -> set[tuple[str, str]]:
    return {
        (row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)
    }


def _flagged(
    rows: Sequence[CfgRow], kind: type[CfgUnresolvedRow] | type[CfgRefusedRow]
) -> list[str]:
    return [row.node for row in rows if isinstance(row, kind)]


def test_a_thru_range_falls_through_its_paragraphs_and_returns(asg_of: Asg) -> None:
    """The range is A THRU B: A's end falls through into B, whose end is the one a
    RETURN leaves from, back to the statement after the PERFORM."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A", "B"), _move("'X'", "WS-X"), {"type": "STOP_RUN"}),
        _para("A", _move("'A'", "WS-A")),
        _para("B", _move("'B'", "WS-B")),
    )

    assert _nodes(rows) == [
        "MAIN/0",
        "A#label",
        "A/0",
        "A#end",
        "B#label",
        "B/0",
        "B#end",
        "MAIN/1",
    ]
    assert _edges(rows) == {
        ("MAIN/0", "A#label", EdgeKind.PERFORM),
        ("A#label", "A/0", EdgeKind.FLOW),
        ("A/0", "A#end", EdgeKind.FLOW),
        ("A#end", "B#label", EdgeKind.FALLTHRU),
        ("B#label", "B/0", EdgeKind.FLOW),
        ("B/0", "B#end", EdgeKind.FLOW),
        ("B#end", "MAIN/1", EdgeKind.RETURN),
    }
    assert _outcomes(rows) == {("returns", "MAIN/1")}
    assert rows[-1] == CfgSummaryRow(type=CfgRowType.SUMMARY, seed="MAIN/0", states=7)


def test_a_range_end_two_sites_share_returns_only_to_the_seeds(asg_of: Asg) -> None:
    """A's end has a RETURN to each PERFORM of it. From the second site, the RETURN
    to the first is never taken, though both its ends are in the subgraph."""
    rows = _rows(
        asg_of,
        "MAIN/1",
        _para("MAIN", _perform("A"), _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _move("'A'", "WS-A")),
    )

    assert _nodes(rows) == ["MAIN/1", "A#label", "A/0", "A#end", "MAIN/2"]
    assert ("A#end", "MAIN/2", EdgeKind.RETURN) in _edges(rows)
    assert ("A#end", "MAIN/1", EdgeKind.RETURN) not in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/2")}


def test_a_nested_perform_returns_to_its_own_site_first(asg_of: Asg) -> None:
    """Inside the range, A performs B. B's end returns to A, and A's end -- which
    would otherwise fall through into B -- returns to the seed."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _perform("B"), _move("'A'", "WS-A")),
        _para("B", _move("'B'", "WS-B")),
    )

    assert _nodes(rows) == [
        "MAIN/0",
        "A#label",
        "A/0",
        "B#label",
        "B/0",
        "B#end",
        "A/1",
        "A#end",
        "MAIN/1",
    ]
    assert {
        ("B#end", "A/1", EdgeKind.RETURN),
        ("A#end", "MAIN/1", EdgeKind.RETURN),
    } <= _edges(rows)
    assert ("A#end", "B#label", EdgeKind.FALLTHRU) not in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/1")}


def test_a_go_to_out_of_the_range_keeps_the_pending_return(asg_of: Asg) -> None:
    """A jumps out of A THRU B to C, and C jumps back to B: B's end still returns,
    because leaving a range by GO TO does not cancel the PERFORM."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A", "B"), {"type": "STOP_RUN"}),
        _para("A", _goto("C")),
        _para("B", _move("'B'", "WS-B")),
        _para("C", _goto("B")),
    )

    assert _paragraphs(rows) == ["MAIN", "A", "C", "B"]
    assert _outcomes(rows) == {("returns", "MAIN/1")}


@pytest.mark.parametrize(
    ("body", "extra", "outcomes"),
    (
        ((({"type": "STOP_RUN"},)), (), {("stop-run", "A/0")}),
        (({"type": "GOBACK"},), (), {("goback", "A/0")}),
        (({"type": "EXIT_PROGRAM"},), (), {("exit-program", "A/0")}),
        (
            (_cics("ABEND", {"ABCODE": {"text": "'AB01'", "is_literal": True}}),),
            (),
            {("abend", "A/0")},
        ),
        (
            (_cics("XCTL", {"PROGRAM": {"text": "'PROGB'", "is_literal": True}}),),
            (),
            {("xctl", "A/0"), ("unhandled-condition", "A/0#dispatch")},
        ),
        (
            (_cics("RETURN", {"RESP": {"text": "WS-RESP", "is_literal": False}}),),
            (),
            {("cics-return", "A/0"), ("returns", "MAIN/1")},
        ),
        ((_goto("Z"),), (_para("Z", _move("'Z'", "WS-Z")),), {("dead-end", "Z#end")}),
    ),
    ids=(
        "stop-run",
        "goback",
        "exit-program",
        "abend",
        "xctl",
        "cics-return-resp",
        "dead-end",
    ),
)
def test_each_way_out_of_the_range_is_an_outcome_at_its_node(
    asg_of: Asg,
    body: tuple[dict, ...],
    extra: tuple[dict, ...],
    outcomes: set[tuple[str, str]],
) -> None:
    """A terminator ends its branch. A successful XCTL or RETURN leaves the program
    from the command itself, and its failure path is walked on: with no handler
    armed the raised condition abends, under RESP the next statement runs. Falling
    off the program's last paragraph is a dead end, not a silent stop. A range
    that cannot return gives no `returns`, and the FLOW edge the build keeps past
    such a PERFORM is not taken."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", *body),
        *extra,
    )

    assert _outcomes(rows) == outcomes
    assert ("MAIN/0", "MAIN/1", EdgeKind.FLOW) not in _edges(rows)


def test_an_end_only_another_site_closes_with_nowhere_to_fall_is_a_dead_end(
    asg_of: Asg,
) -> None:
    """A jumps to Z, the last paragraph. Z's end returns only to the second PERFORM's
    site, which is not the innermost open frame here, and there is no next
    paragraph to fall into: the branch is a dead end at Z's end, recorded."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), _perform("Z"), {"type": "STOP_RUN"}),
        _para("A", _goto("Z")),
        _para("Z", _move("'Z'", "WS-Z")),
    )

    assert _outcomes(rows) == {("dead-end", "Z#end")}
    assert ("Z#end", "MAIN/2", EdgeKind.RETURN) not in _edges(rows)


def test_two_performs_resuming_at_one_statement_do_not_return_for_each_other(
    asg_of: Asg,
) -> None:
    """Both arms of an IF perform a range and resume at the same next statement. A
    jumps into B's range; B's end returns only for the PERFORM of B, which never
    ran on this path, so control falls through to Z and stops there -- the walk
    must not take B's RETURN as A's."""
    rows = _rows(
        asg_of,
        "MAIN/0.then.0",
        _para(
            "MAIN",
            _if(_perform("A"), _perform("B")),
            _move("'X'", "WS-X"),
            {"type": "STOP_RUN"},
        ),
        _para("A", _goto("B")),
        _para("B", _move("'B'", "WS-B")),
        _para("Z", {"type": "STOP_RUN"}),
    )

    assert _outcomes(rows) == {("stop-run", "Z/0")}
    assert ("B#end", "MAIN/1", EdgeKind.RETURN) not in _edges(rows)


def test_a_go_to_an_outer_ranges_exit_returns_from_the_outer_perform(
    asg_of: Asg,
) -> None:
    """Inside P2's range, a GO TO reaches P1-EXIT, the end of the outer range: the
    outer PERFORM returns from there, and the inner one it abandoned is dropped."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("P1", "P1-EXIT"), {"type": "STOP_RUN"}),
        _para("P1", _perform("P2", "P2-EXIT")),
        _para("P1-EXIT", {"type": "EXIT"}),
        _para("P2", _goto("P1-EXIT")),
        _para("P2-EXIT", {"type": "EXIT"}),
        _para("LAST", {"type": "STOP_RUN"}),
    )

    assert _outcomes(rows) == {("returns", "MAIN/1")}
    assert ("P1-EXIT#end", "MAIN/1", EdgeKind.RETURN) in _edges(rows)


def test_a_handled_condition_reaches_its_handler_and_the_loop_back_ends(
    asg_of: Asg,
) -> None:
    """The dispatch's edge to the armed handler is followed. The handler's own XCTL
    raises back into it -- the arming is still live there -- and the walk records
    that edge once and stops, since the state it reaches is already visited."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "GOBACK"}),
        _para(
            "A",
            _cics("HANDLE CONDITION", {"MAPFAIL": {"text": "H", "is_literal": False}}),
            _cics("RECEIVE MAP", {"MAP": {"text": "'M'", "is_literal": True}}),
        ),
        _para("H", _cics("XCTL", {"PROGRAM": {"text": "'PROGB'", "is_literal": True}})),
    )

    assert _paragraphs(rows) == ["MAIN", "A", "H"]
    assert _outcomes(rows) == {("returns", "MAIN/1"), ("xctl", "H/0")}
    assert [
        (row.source, row.target)
        for row in rows
        if isinstance(row, CfgEdgeRow) and row.source == "H/0#dispatch"
    ] == [("H/0#dispatch", "H#label")]


def test_a_recursive_perform_is_refused_and_stepped_over(asg_of: Asg) -> None:
    """A performs A. The first time it is a real nested PERFORM; inside that, A's
    resume point is already open, so the PERFORM is refused and the walk resumes
    after it, as if the range had run."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _perform("A"), _move("'A'", "WS-A")),
    )

    assert _flagged(rows, CfgRefusedRow) == ["A/0"]
    assert ("A/0", "A/1", EdgeKind.FLOW) in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/1")}


def test_an_unresolved_perform_is_recorded_and_stepped_past(asg_of: Asg) -> None:
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _perform("NOWHERE"), _move("'A'", "WS-A")),
    )

    assert _flagged(rows, CfgUnresolvedRow) == ["A/0"]
    assert ("A/0", "A/1", EdgeKind.FLOW) in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/1")}


@pytest.mark.parametrize(
    ("seed", "message"),
    (
        ("MAIN/9", "PROGA has no node MAIN/9"),
        ("MAIN/1", r"MAIN/1 is not a PERFORM \(kind ASSIGN, transfer MOVE\)"),
        ("MAIN/2", "MAIN/2 performs NOWHERE, which PROGA does not declare"),
    ),
    ids=("absent", "not-a-perform", "unresolved"),
)
def test_a_seed_that_is_not_a_resolved_perform_is_refused_before_any_row(
    asg_of: Asg, seed: str, message: str
) -> None:
    cfg = program_cfg(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    _para(
                        "MAIN",
                        _perform("A"),
                        _move("'X'", "WS-X"),
                        _perform("NOWHERE"),
                        {"type": "STOP_RUN"},
                    ),
                    _para("A", _move("'A'", "WS-A")),
                ],
            }
        )
    )

    with pytest.raises(ReachError, match=message):
        reach_rows(cfg, seed)


def test_rows_stream_nodes_before_their_edges_and_the_summary_last(asg_of: Asg) -> None:
    """Any prefix of the output is a valid partial graph, and only a finished walk
    ends in a summary."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A", "B"), {"type": "STOP_RUN"}),
        _para("A", _goto("C")),
        _para("B", _move("'B'", "WS-B")),
        _para("C", _goto("B")),
    )
    position = {
        row.id: at for at, row in enumerate(rows) if isinstance(row, CfgNodeRow)
    }

    assert rows[0].type is CfgRowType.PROGRAM
    assert all(
        position[row.source] < at and position[row.target] < at
        for at, row in enumerate(rows)
        if isinstance(row, CfgEdgeRow)
    )
    assert [row.type for row in rows].count(CfgRowType.SUMMARY) == 1
    assert isinstance(rows[-1], CfgSummaryRow)
