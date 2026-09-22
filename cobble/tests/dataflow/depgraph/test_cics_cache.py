"""Reading EXEC CICS back out of the parsed-ASG cache.

The cache holds ``ExecCicsStatement.to_dict()``, which has no ``exec_cics_text``
for cicada's bridge-JSON parser to work from, so cobble registers its own parser
for that form ahead of it. What the two must agree on is the operand: a
subscripted callee that arrives here as a bare name resolves at arity 0 against a
field declared OCCURS and matches no cell (forge-zgn).
"""

from __future__ import annotations

from cics.statements import CicsOperand
from cobble.dataflow.depgraph.cics_cache import SerializedCicsDialectParser
from cobol_asg.cobol_expression import FieldRefNode


def _parsed(options: dict):
    return SerializedCicsDialectParser().parse(
        {"type": "EXEC_CICS", "verb": "XCTL", "options": options}
    )


def test_the_serialized_form_is_the_one_this_parser_claims() -> None:
    """Bridge JSON has no ``verb``; cicada's parser must keep handling that."""
    parser = SerializedCicsDialectParser()

    assert parser.applies({"type": "EXEC_CICS", "verb": "XCTL"}) is True
    assert parser.applies({"type": "EXEC_CICS", "exec_cics_text": "..."}) is False


def test_a_subscripted_callee_keeps_its_index_out_of_the_cache() -> None:
    statement = _parsed(
        {
            "PROGRAM": {
                "text": "CDEMO-MENU-OPT-PGMNAME",
                "is_literal": False,
                "subscripts": [{"kind": "ref", "name": "WS-OPTION"}],
            }
        }
    )

    assert statement.options["PROGRAM"] == CicsOperand(
        text="CDEMO-MENU-OPT-PGMNAME",
        is_literal=False,
        subscripts=(FieldRefNode(name="WS-OPTION"),),
    )


def test_an_unsubscripted_callee_reads_back_as_the_scalar_it_is() -> None:
    """Every ASG cached before the structure was written carries these two keys
    alone, and has to keep reading back unchanged."""
    statement = _parsed({"PROGRAM": {"text": "CDEMO-TO-PROGRAM", "is_literal": False}})

    assert statement.options["PROGRAM"] == CicsOperand(
        text="CDEMO-TO-PROGRAM", is_literal=False
    )


def test_a_bare_flag_stays_a_key_with_no_operand_behind_it() -> None:
    statement = _parsed(
        {"PROGRAM": {"text": "WS-PROG", "is_literal": False}, "NOHANDLE": None}
    )

    assert statement.options["NOHANDLE"] is None
