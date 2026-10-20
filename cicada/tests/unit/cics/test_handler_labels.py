"""The HANDLE/IGNORE label pre-pass: procedure label to dispatch index."""

from __future__ import annotations

from cics.cics_parser import CicsOperand
from cics.handler_labels import collect_handler_labels, paragraph_names
from cics.statements import ExecCicsStatement
from interpreter.cobol.procedure_labels import ProcedureLabels
from interpreter.ir import CodeLabel

NO_SECTIONS = ProcedureLabels()


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

    assert collect_handler_labels(stmts, NO_SECTIONS).indices == {
        CodeLabel("para_PARA-A"): 1,
        CodeLabel("para_PARA-B"): 2,
        CodeLabel("para_PARA-C"): 3,
    }


def test_a_paragraph_named_twice_keeps_one_index():
    """Two conditions handled by the same paragraph share its index."""
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION",
            options={"NOTFND": _operand("PARA-A"), "ERROR": _operand("PARA-A")},
        )
    ]

    assert collect_handler_labels(stmts, NO_SECTIONS).indices == {
        CodeLabel("para_PARA-A"): 1
    }


def test_ignore_contributes_no_label():
    """IGNORE CONDITION cancels a handler; it names no paragraph."""
    stmts = [
        ExecCicsStatement(verb="IGNORE CONDITION", options={"NOTFND": None}),
    ]

    assert collect_handler_labels(stmts, NO_SECTIONS).indices == {}


def test_other_verbs_are_not_scanned():
    """A READ's FILE operand is not a handler label."""
    stmts = [ExecCicsStatement(verb="READ", options={"FILE": _operand("ACCTFILE")})]

    assert collect_handler_labels(stmts, NO_SECTIONS).indices == {}


def test_a_program_with_no_handlers_yields_an_empty_map():
    assert collect_handler_labels([], NO_SECTIONS).indices == {}


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

    assert collect_handler_labels(stmts, NO_SECTIONS).conditions == {
        "PARA-A": "NOTFND",
        "PARA-B": "ERROR",
    }


def test_a_target_name_folds_case_as_a_procedure_reference_does():
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION", options={"NOTFND": _operand("para-missing")}
        )
    ]

    labels = collect_handler_labels(stmts, NO_SECTIONS)

    assert (labels.indices, labels.conditions) == (
        {CodeLabel("para_PARA-MISSING"): 1},
        {"PARA-MISSING": "NOTFND"},
    )


def test_a_section_target_is_the_section_label():
    stmts = [
        ExecCicsStatement(verb="HANDLE CONDITION", options={"ERROR": _operand("S1")})
    ]
    procedures = ProcedureLabels(sections={"S1": ("PARA-A",)})

    assert collect_handler_labels(stmts, procedures).indices == {
        CodeLabel("section_S1"): 1
    }


def test_each_sections_copy_of_a_duplicated_paragraph_gets_its_own_index():
    """The HANDLE statement's own section decides which copy it means, and that
    is only known while lowering it, so every copy is numbered up front."""
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION", options={"NOTFND": _operand("ERR-PARA")}
        )
    ]
    procedures = ProcedureLabels(
        sections={"SEC-A": ("ERR-PARA",), "SEC-B": ("ERR-PARA",)},
        duplicated=frozenset({"ERR-PARA"}),
    )

    assert collect_handler_labels(stmts, procedures).indices == {
        CodeLabel("para_SEC-A_ERR-PARA"): 1,
        CodeLabel("para_SEC-B_ERR-PARA"): 2,
    }


def test_abend_exits_are_labels():
    stmts = [
        ExecCicsStatement(verb="HANDLE ABEND", options={"LABEL": _operand("err-x")})
    ]

    assert collect_handler_labels(stmts, NO_SECTIONS).abend_exits == frozenset(
        {CodeLabel("para_ERR-X")}
    )


def test_abend_exit_handlers_are_in_index_order():
    stmts = [
        ExecCicsStatement(verb="HANDLE ABEND", options={"LABEL": _operand("ERR-Z")}),
        ExecCicsStatement(
            verb="HANDLE CONDITION", options={"NOTFND": _operand("PARA-A")}
        ),
        ExecCicsStatement(verb="HANDLE ABEND", options={"LABEL": _operand("ERR-B")}),
    ]

    assert collect_handler_labels(stmts, NO_SECTIONS).abend_exit_handlers() == (
        (CodeLabel("para_ERR-Z"), 1),
        (CodeLabel("para_ERR-B"), 3),
    )


def test_paragraph_names_span_standalone_sectioned_and_declarative():
    """A HANDLE target may be any of the three, and only the raw bridge dict has
    all of them — ctx.section_paragraphs omits standalone paragraphs entirely."""
    program = {
        "paragraphs": [{"name": "PARA-A"}],
        "sections": [{"name": "S1", "paragraphs": [{"name": "PARA-B"}]}],
        "declaratives": [{"name": "D1", "paragraphs": [{"name": "PARA-C"}]}],
    }

    assert paragraph_names(program) == frozenset({"PARA-A", "PARA-B", "PARA-C"})


def test_paragraph_names_fold_case():
    program = {"paragraphs": [{"name": "Para-Missing"}]}

    assert paragraph_names(program) == frozenset({"PARA-MISSING"})


def test_a_program_with_no_paragraphs_names_none():
    assert paragraph_names({"statements": []}) == frozenset()
