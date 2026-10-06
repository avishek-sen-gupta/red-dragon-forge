"""cobble-srccfg-dfs-walk's two walks: the same stepper as
cobble-srccfg-reachability-walk, driven depth-first instead of
level-by-level -- over CFGs built the way cobble-srccfg-build builds them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.reach.dfs import primary_walk, tree_walk
from cobol_asg.asg_types import CobolASG

Asg = Callable[[Mapping], CobolASG]


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _perform(target: str) -> dict:
    return {"type": "PERFORM", "operands": [target]}


def _goto(target: str) -> dict:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


def _goback() -> dict:
    return {"type": "GOBACK"}


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


def _cfg(asg_of: Asg, *paragraphs: dict):
    return program_cfg(asg_of({"program_id": "PROGA", "paragraphs": list(paragraphs)}))


def test_a_straight_line_visits_every_paragraph_once_in_seed_first_order(
    asg_of: Asg,
) -> None:
    """The seed's own paragraph is noted before anything stepped into -- same as
    cobble-srccfg-reachability-walk's own first row."""
    cfg = _cfg(
        asg_of,
        _para("MAIN", _perform("A")),
        _para("A", _perform("B")),
        _para("B", _goback()),
    )

    _, order = primary_walk(cfg, "MAIN/0")

    assert order == ["MAIN", "A", "B"]


def test_a_straight_line_reports_the_goback_outcome_at_its_node(asg_of: Asg) -> None:
    cfg = _cfg(
        asg_of,
        _para("MAIN", _perform("A")),
        _para("A", _perform("B")),
        _para("B", _goback()),
    )

    lines, _ = primary_walk(cfg, "MAIN/0")

    assert any("outcome: goback" in line and "B/0" in line for line in lines)


def test_primary_mode_takes_the_true_arm_and_notes_the_false_alternate(
    asg_of: Asg,
) -> None:
    """IF's TRUE arm is COBOL's own THEN-before-ELSE order; the FALSE arm is noted
    inline, not expanded into its own lines."""
    cfg = _cfg(
        asg_of,
        _para("MAIN", _perform("A")),
        _para("A", _if(_move("X", "Y"), _move("P", "Q"))),
    )

    lines, order = primary_walk(cfg, "MAIN/0")

    assert order == ["MAIN", "A"]
    decision = next(line for line in lines if "decision at" in line)
    assert "A/0.then.0" in decision
    assert "FALSE->A/0.else.0" in decision
    assert not any("A/0.else.0" in line and "decision" not in line for line in lines)


def test_tree_mode_recurses_both_arms_of_the_branch(asg_of: Asg) -> None:
    cfg = _cfg(
        asg_of,
        _para("MAIN", _perform("A")),
        _para("A", _if(_move("X", "Y"), _move("P", "Q"))),
    )

    lines, order = tree_walk(cfg, "MAIN/0")

    assert order == ["MAIN", "A"]
    assert any("A/0.then.0" in line and "branch 1/2" in line for line in lines)
    assert any("A/0.else.0" in line and "branch 2/2" in line for line in lines)


def test_tree_mode_cuts_off_a_self_loop_and_says_so(asg_of: Asg) -> None:
    cfg = _cfg(
        asg_of,
        _para("MAIN", _perform("A")),
        _para("A", _goto("A")),
    )

    lines, _ = tree_walk(cfg, "MAIN/0")

    assert any("loop/converge" in line for line in lines)


def test_primary_mode_cuts_off_a_self_loop_and_says_so(asg_of: Asg) -> None:
    cfg = _cfg(
        asg_of,
        _para("MAIN", _perform("A")),
        _para("A", _goto("A")),
    )

    lines, _ = primary_walk(cfg, "MAIN/0")

    assert any("loop closes here" in line for line in lines)


def test_a_dead_end_leaving_outcome_is_reported_and_never_returns(asg_of: Asg) -> None:
    """XCTL leaves the task entirely -- the walk must not pretend it falls back to
    MAIN; MAIN never gets noted."""
    cfg = _cfg(
        asg_of,
        _para("MAIN", _perform("A")),
        _para(
            "A",
            {
                "type": "EXEC_CICS",
                "verb": "XCTL",
                "options": {"PROGRAM": {"kind": "lit", "value": "'OTHERPGM'"}},
            },
        ),
    )

    lines, order = primary_walk(cfg, "MAIN/0")

    assert any("outcome: xctl" in line for line in lines)
    assert order == ["MAIN", "A"]
