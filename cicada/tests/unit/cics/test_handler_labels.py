"""The HANDLE/IGNORE label pre-pass: paragraph name to dispatch index."""

from __future__ import annotations

from cics.handler_labels import collect_handler_labels, paragraph_names
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

    assert collect_handler_labels(stmts).indices == {
        "PARA-A": 1,
        "PARA-B": 2,
        "PARA-C": 3,
    }


def test_a_paragraph_named_twice_keeps_one_index():
    """Two conditions handled by the same paragraph share its index."""
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION",
            options={"NOTFND": _operand("PARA-A"), "ERROR": _operand("PARA-A")},
        )
    ]

    assert collect_handler_labels(stmts).indices == {"PARA-A": 1}


def test_ignore_contributes_no_label():
    """IGNORE CONDITION cancels a handler; it names no paragraph."""
    stmts = [
        ExecCicsStatement(verb="IGNORE CONDITION", options={"NOTFND": None}),
    ]

    assert collect_handler_labels(stmts).indices == {}


def test_other_verbs_are_not_scanned():
    """A READ's FILE operand is not a handler label."""
    stmts = [ExecCicsStatement(verb="READ", options={"FILE": _operand("ACCTFILE")})]

    assert collect_handler_labels(stmts).indices == {}


def test_a_program_with_no_handlers_yields_an_empty_map():
    assert collect_handler_labels([]).indices == {}


def test_the_condition_that_named_each_paragraph_is_kept():
    """The compile-time rejection of an undefined target names the condition the
    program wrote, so the first condition naming a paragraph is carried with it."""
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION",
            options={"NOTFND": _operand("PARA-A"), "ERROR": _operand("PARA-B")},
        ),
        ExecCicsStatement(
            verb="HANDLE CONDITION", options={"LENGERR": _operand("PARA-A")}
        ),
    ]

    assert collect_handler_labels(stmts).conditions == {
        "PARA-A": "NOTFND",
        "PARA-B": "ERROR",
    }


def test_paragraph_names_span_standalone_sectioned_and_declarative():
    """A HANDLE target may be any of the three, and only the raw bridge dict has
    all of them — ctx.section_paragraphs omits standalone paragraphs entirely."""
    program = {
        "paragraphs": [{"name": "PARA-A"}],
        "sections": [{"name": "S1", "paragraphs": [{"name": "PARA-B"}]}],
        "declaratives": [{"name": "D1", "paragraphs": [{"name": "PARA-C"}]}],
    }

    assert paragraph_names(program) == frozenset({"PARA-A", "PARA-B", "PARA-C"})


def test_a_program_with_no_paragraphs_names_none():
    assert paragraph_names({"statements": []}) == frozenset()
