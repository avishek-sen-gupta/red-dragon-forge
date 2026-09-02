from interpreter.cobol.cobol_expression import LiteralNode
from interpreter.cobol.ref_mod import (
    RefModBinOp,
    RefModLengthOf,
    RefModLiteral,
    RefModOperand,
    RefModReference,
    ref_mod_expr_from_dict,
)


def test_ref_mod_expr_from_dict_literal() -> None:
    assert ref_mod_expr_from_dict({"kind": "lit", "value": "2"}) == RefModLiteral(
        value="2"
    )


def test_ref_mod_expr_from_dict_reference() -> None:
    assert ref_mod_expr_from_dict({"kind": "ref", "name": "WS-A"}) == RefModReference(
        name="WS-A"
    )


def test_ref_mod_expr_from_dict_length_of() -> None:
    assert ref_mod_expr_from_dict(
        {"kind": "length_of", "name": "WS-A"}
    ) == RefModLengthOf(name="WS-A")


def test_ref_mod_expr_from_dict_binop_recurses() -> None:
    node = ref_mod_expr_from_dict(
        {
            "kind": "binop",
            "op": "+",
            "left": {"kind": "ref", "name": "WS-A"},
            "right": {"kind": "lit", "value": "1"},
        }
    )
    assert node == RefModBinOp(
        op="+", left=RefModReference(name="WS-A"), right=RefModLiteral(value="1")
    )


def test_ref_mod_expr_from_dict_unknown_kind_defaults_to_empty_literal() -> None:
    assert ref_mod_expr_from_dict({"kind": "bogus"}) == RefModLiteral(value="")


def test_ref_mod_operand_from_dict_bare_field() -> None:
    operand = RefModOperand.from_dict({"name": "WS-FIELD"})
    assert operand == RefModOperand(name="WS-FIELD")


def test_ref_mod_operand_from_dict_legacy_string_format() -> None:
    assert RefModOperand.from_dict("WS-FIELD") == RefModOperand(name="WS-FIELD")


def test_ref_mod_operand_from_dict_with_start_and_length() -> None:
    operand = RefModOperand.from_dict(
        {
            "name": "WS-FIELD",
            "ref_mod_start": {"kind": "lit", "value": "2"},
            "ref_mod_length": {"kind": "lit", "value": "3"},
        }
    )
    assert operand.ref_mod_start == RefModLiteral(value="2")
    assert operand.ref_mod_length == RefModLiteral(value="3")


def test_ref_mod_operand_from_dict_length_of_source_leaves_name_empty() -> None:
    operand = RefModOperand.from_dict({"kind": "length_of", "name": "WS-A"})
    assert operand.name == ""
    assert operand.length_of == "WS-A"


def test_ref_mod_operand_from_dict_with_subscripts() -> None:
    operand = RefModOperand.from_dict(
        {
            "name": "WS-TABLE",
            "subscripts": [{"kind": "lit", "value": "1"}],
        }
    )
    assert operand.subscripts == (LiteralNode(value="1"),)


def test_ref_mod_operand_to_dict_round_trips_start_and_length() -> None:
    data = {
        "name": "WS-FIELD",
        "ref_mod_start": {"kind": "lit", "value": "2"},
        "ref_mod_length": {"kind": "lit", "value": "3"},
    }
    assert RefModOperand.from_dict(data).to_dict() == data


def test_ref_mod_operand_to_dict_length_of_source() -> None:
    operand = RefModOperand(name="", length_of="WS-A")
    assert operand.to_dict() == {"kind": "length_of", "name": "WS-A"}
