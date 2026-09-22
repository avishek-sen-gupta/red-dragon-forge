"""The structure cobble keeps for an EXEC CICS option operand.

cicada splits an operand into a bare ``text`` and structured ``subscripts`` on
purpose, and its own serializer keeps only the first half. cobble's every stage
after the parse reads the cache rather than the source, so the half it dropped was
the half that says WHICH occurrence of a table a callee names (forge-zgn).
"""

from __future__ import annotations

from cics.statements import CicsOperand
from cobble.cics.cics_operand import (
    as_reference,
    as_written,
    operand_from_dict,
    operand_to_dict,
)
from cobble.dataflow.depgraph.cics_cache import SerializedCicsDialectParser
from cobol_asg.cobol_expression import FieldRefNode, LiteralNode

SUBSCRIPTED = CicsOperand(
    text="CDEMO-MENU-OPT-PGMNAME",
    is_literal=False,
    subscripts=(FieldRefNode(name="WS-OPTION"),),
)
PLAIN = CicsOperand(text="CDEMO-TO-PROGRAM", is_literal=False)
LITERAL = CicsOperand(text="COMEN01C", is_literal=True)


def test_a_plain_operand_serializes_to_exactly_the_two_keys_it_always_did() -> None:
    """Every unsubscripted site has to produce the cache entry it produced before,
    or the whole corpus's ASGs would have to be reparsed to stay comparable."""
    assert operand_to_dict(PLAIN) == {"text": "CDEMO-TO-PROGRAM", "is_literal": False}


def test_a_literal_operand_serializes_unchanged() -> None:
    assert operand_to_dict(LITERAL) == {"text": "COMEN01C", "is_literal": True}


def test_a_subscripted_operand_keeps_its_index_through_the_cache() -> None:
    assert operand_from_dict(operand_to_dict(SUBSCRIPTED)) == SUBSCRIPTED


def test_a_reference_modified_operand_keeps_both_bounds_through_the_cache() -> None:
    operand = CicsOperand(
        text="WS-AREA",
        is_literal=False,
        ref_mod_start=LiteralNode(value="2"),
        ref_mod_length=LiteralNode(value="3"),
    )

    assert operand_from_dict(operand_to_dict(operand)) == operand


def test_a_bare_flag_stays_a_key_with_no_operand_behind_it() -> None:
    """NOHANDLE and RESP carry no value and serialize as null, which is the same
    thing cicada's own parser produces for them."""
    statement = SerializedCicsDialectParser().parse(
        {
            "type": "EXEC_CICS",
            "verb": "INQUIRE",
            "options": {
                "PROGRAM": {"text": "WS-PROG", "is_literal": False},
                "NOHANDLE": None,
            },
        }
    )

    assert statement.options["NOHANDLE"] is None
    assert statement.options["PROGRAM"] == CicsOperand(text="WS-PROG", is_literal=False)


def test_an_operand_cached_before_this_existed_still_reads() -> None:
    entry = {"text": "WS-PROG", "is_literal": False}

    assert operand_from_dict(entry) == CicsOperand(text="WS-PROG", is_literal=False)


def test_a_subscripted_operand_resolves_as_storage_at_its_own_arity() -> None:
    reference = as_reference(SUBSCRIPTED)

    assert (reference.name, len(reference.subscripts)) == (
        "CDEMO-MENU-OPT-PGMNAME",
        1,
    )


def test_a_plain_operand_resolves_as_the_scalar_it_is() -> None:
    reference = as_reference(PLAIN)

    assert (reference.name, reference.subscripts) == ("CDEMO-TO-PROGRAM", ())


def test_a_subscripted_operand_is_written_with_its_index() -> None:
    assert as_written(SUBSCRIPTED) == "CDEMO-MENU-OPT-PGMNAME(WS-OPTION)"


def test_a_plain_operand_is_written_as_its_name_alone() -> None:
    assert as_written(PLAIN) == "CDEMO-TO-PROGRAM"
