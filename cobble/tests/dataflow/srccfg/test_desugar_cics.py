"""EXEC CICS: arming a handler, and a command that can raise.

Arming is an assignment to a synthetic field, and dispatch is a test on it. That is
the whole trick: PUSH HANDLE, re-arming inside a loop, and "which handler is live
here" all become reaching definitions over %HANDLER[...], with no third node kind
and no separate handler model.
"""

from __future__ import annotations

import pytest

from cobble.dataflow.depgraph.flows import program_context
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import (
    DISPATCH_TRANSFER_CICS,
    Ctx,
    lower_statements,
)
from cobble.dataflow.srccfg.synthetic import (
    HANDLER_ANY,
    IGNORED,
    RAISED,
    SYSTEM_DEFAULT,
    handler_field,
)


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _cfg(program_of, statements: list[dict]) -> Cfg:
    asg = program_of(statements)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(
        program="PROGA",
        nodes=fragment.nodes,
        edges=fragment.edges,
        entry=fragment.entry,
    )


def _cics(verb: str, options: dict) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": options}


def test_handle_condition_writes_the_handler_field_and_reads_the_paragraph(
    program_of,
) -> None:
    cfg = _cfg(
        program_of,
        [
            _cics(
                "HANDLE CONDITION",
                {"MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False}},
            )
        ],
    )

    node = cfg.node("MAIN/0")
    assert (node.kind, node.writes, node.reads) == (
        NodeKind.ASSIGN,
        (handler_field("MAPFAIL"),),
        ("9999-MAPFAIL",),
    )


def test_arming_two_conditions_in_one_command_writes_both_fields(program_of) -> None:
    """One statement, two definitions -- and they are independent, so a later
    re-arming of one must not look like a re-arming of the other."""
    cfg = _cfg(
        program_of,
        [
            _cics(
                "HANDLE CONDITION",
                {
                    "MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False},
                    "ERROR": {"text": "9999-ERROR", "is_literal": False},
                },
            )
        ],
    )

    assert cfg.node("MAIN/0").writes == (
        handler_field("MAPFAIL"),
        handler_field("ERROR"),
    )


def test_a_condition_armed_with_no_paragraph_resets_to_the_system_default(
    program_of,
) -> None:
    """HANDLE CONDITION ERROR with no label disarms the program's own handler. That
    is a definition, and the value it writes has to be distinguishable from a
    paragraph name."""
    cfg = _cfg(program_of, [_cics("HANDLE CONDITION", {"ERROR": None})])

    assert cfg.node("MAIN/0").reads == (SYSTEM_DEFAULT,)


def test_ignore_condition_writes_the_ignore_marker(program_of) -> None:
    """IGNORE CONDITION means "do not transfer control", which is a different live
    value from "no handler armed" -- the command returns and execution continues."""
    cfg = _cfg(program_of, [_cics("IGNORE CONDITION", {"MAPFAIL": None})])

    node = cfg.node("MAIN/0")
    assert (node.writes, node.reads) == ((handler_field("MAPFAIL"),), (IGNORED,))


def test_a_command_that_can_raise_gets_a_test_and_a_dispatch_node(program_of) -> None:
    """The dispatch has no target yet: which handler is live here is a
    reaching-definitions question over %HANDLER[...], answered by a later pass."""
    cfg = _cfg(
        program_of,
        [_cics("RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}})],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert (test_node.atom.left, test_node.atom.right) == (HANDLER_ANY, RAISED)
    dispatch = cfg.node("MAIN/0#dispatch")
    assert (dispatch.transfer, dispatch.target) == (DISPATCH_TRANSFER_CICS, "")
    assert dispatch.reads == (HANDLER_ANY,)


def test_the_dispatch_node_has_no_outgoing_edge_of_its_own(program_of) -> None:
    """Control leaves for a handler paragraph, so the node ends its path -- exactly
    like a GO TO, and for the same reason."""
    cfg = _cfg(
        program_of,
        [
            _cics("RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}}),
            {"type": "MOVE", "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}]},
        ],
    )

    assert cfg.successors("MAIN/0#dispatch") == ()
    assert [e.kind for e in cfg.predecessors("MAIN/1")] == [EdgeKind.FALSE]


_PROGRAM = {"PROGRAM": {"text": "'PROGB'", "is_literal": True}}
_RESP = {"RESP": {"text": "WS-RESP", "is_literal": False}}


@pytest.mark.parametrize(
    ("verb", "options", "edges"),
    [
        (
            "LINK",
            _PROGRAM,
            {
                ("MAIN/0", "MAIN/0#raise", EdgeKind.FLOW),
                ("MAIN/0#raise", "MAIN/0#dispatch", EdgeKind.TRUE),
                ("MAIN/0#raise", "MAIN/1", EdgeKind.FALSE),
            },
        ),
        (
            "XCTL",
            _PROGRAM,
            {
                ("MAIN/0", "MAIN/0#raise", EdgeKind.FLOW),
                ("MAIN/0#raise", "MAIN/0#dispatch", EdgeKind.TRUE),
            },
        ),
        (
            "RETURN",
            {},
            {
                ("MAIN/0", "MAIN/0#raise", EdgeKind.FLOW),
                ("MAIN/0#raise", "MAIN/0#dispatch", EdgeKind.TRUE),
            },
        ),
        ("XCTL", {**_PROGRAM, **_RESP}, {("MAIN/0", "MAIN/1", EdgeKind.FLOW)}),
        ("RETURN", {**_RESP}, {("MAIN/0", "MAIN/1", EdgeKind.FLOW)}),
        ("ABEND", {"ABCODE": {"text": "'AB01'", "is_literal": True}}, set()),
    ],
)
def test_a_command_that_leaves_the_program_continues_only_when_it_fails(
    program_of, verb: str, options: dict, edges: set
) -> None:
    """A successful XCTL or RETURN never comes back, so the raise test's
    nothing-raised arm reaches nothing; a failure still goes to the handler, or,
    under RESP or NOHANDLE, on to the next statement. ABEND raises no condition and
    never returns, so it ends the path outright. LINK returns, and keeps both."""
    cfg = _cfg(
        program_of,
        [
            _cics(verb, options),
            {"type": "MOVE", "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}]},
        ],
    )

    assert {(e.source, e.target, e.kind) for e in cfg.edges} == edges


def test_nohandle_suppresses_the_raise_test(program_of) -> None:
    """NOHANDLE means the command cannot transfer control, so there is no fork here
    at all -- and a test node would make every following assignment read as
    conditional on nothing."""
    cfg = _cfg(
        program_of,
        [
            _cics(
                "READ",
                {"FILE": {"text": "'CUSTFILE'", "is_literal": True}, "NOHANDLE": None},
            )
        ],
    )

    assert [n.kind for n in cfg.nodes if n.kind == NodeKind.TEST] == []


def test_a_resp_option_suppresses_the_raise_test_too(program_of) -> None:
    """RESP is the modern form of the same thing: the command sets a field instead
    of transferring, and the program tests that field itself -- which shows up as a
    real IF, so a synthetic fork here would double-count it."""
    cfg = _cfg(
        program_of,
        [
            _cics(
                "READ",
                {
                    "FILE": {"text": "'CUSTFILE'", "is_literal": True},
                    "RESP": {"text": "WS-RESP", "is_literal": False},
                },
            )
        ],
    )

    assert [n.kind for n in cfg.nodes if n.kind == NodeKind.TEST] == []


def test_arming_a_handler_is_not_itself_a_command_that_can_raise(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _cics(
                "HANDLE CONDITION",
                {"MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False}},
            )
        ],
    )

    assert len(cfg.nodes) == 1


def test_a_cics_commands_own_dataflow_is_still_read(program_of) -> None:
    """flows already knows what SEND MAP moves; the raise test is added around that
    answer, not instead of it."""
    cfg = _cfg(
        program_of,
        [
            _cics(
                "SEND MAP",
                {
                    "MAP": {"text": "'MAPA'", "is_literal": True},
                    "FROM": {"text": "WS-MAP-AREA", "is_literal": False},
                },
            )
        ],
    )

    assert "WS-MAP-AREA" in cfg.node("MAIN/0").reads


def test_full_program_assembly_leaves_handler_edges_and_dispatch_target_intact(
    program_of,
) -> None:
    """The edge invariant lives in test_build_paragraphs, so without this the new
    node kinds have no coverage under full program assembly."""
    asg = program_of(
        [
            _cics(
                "HANDLE CONDITION",
                {"MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False}},
            ),
            _cics("RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}}),
        ],
        paragraphs=[
            {
                "name": "MAIN",
                "statements": [
                    _cics(
                        "HANDLE CONDITION",
                        {"MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False}},
                    ),
                    _cics(
                        "RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}}
                    ),
                ],
            },
            {"name": "9999-MAPFAIL", "statements": []},
        ],
    )
    cfg = build_program(asg)

    bad_edges = tuple(
        e
        for e in cfg.edges
        if e.source not in cfg.node_ids or e.target not in cfg.node_ids
    )
    assert bad_edges == ()

    dispatch = next(n for n in cfg.nodes if n.id.endswith("#dispatch"))
    assert dispatch.target == ""
