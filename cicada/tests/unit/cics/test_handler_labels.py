"""The HANDLE/IGNORE label pre-pass: paragraph name to dispatch index."""

from __future__ import annotations

from cics.handler_labels import collect_handler_labels
from cics.cics_parser import CicsOperand
from cics.statements import ExecCicsStatement


def _operand(text: str) -> CicsOperand:
    return CicsOperand(text=text, is_literal=False)


def test_labels_are_numbered_from_one_in_first_appearance_order():
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION",
            options={"NOTFND": _operand("PARA-A"), "ERROR": _operand("PARA-B")},
        ),
        ExecCicsStatement(
            verb="HANDLE CONDITION", options={"LENGERR": _operand("PARA-C")}
        ),
    ]

    assert collect_handler_labels(stmts) == {"PARA-A": 1, "PARA-B": 2, "PARA-C": 3}


def test_a_paragraph_named_twice_keeps_one_index():
    """Two conditions handled by the same paragraph share its index."""
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION",
            options={"NOTFND": _operand("PARA-A"), "ERROR": _operand("PARA-A")},
        )
    ]

    assert collect_handler_labels(stmts) == {"PARA-A": 1}


def test_ignore_contributes_no_label():
    """IGNORE CONDITION cancels a handler; it names no paragraph."""
    stmts = [
        ExecCicsStatement(verb="IGNORE CONDITION", options={"NOTFND": None}),
    ]

    assert collect_handler_labels(stmts) == {}


def test_other_verbs_are_not_scanned():
    """A READ's FILE operand is not a handler label."""
    stmts = [ExecCicsStatement(verb="READ", options={"FILE": _operand("ACCTFILE")})]

    assert collect_handler_labels(stmts) == {}


def test_a_program_with_no_handlers_yields_an_empty_map():
    assert collect_handler_labels([]) == {}
