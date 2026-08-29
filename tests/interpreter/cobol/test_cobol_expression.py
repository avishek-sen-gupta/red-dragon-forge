import pytest

from cobble.interpreter.cobol.cobol_expression import (
    BinOpNode,
    DfhRespNode,
    FieldRefNode,
    FigurativeNode,
    FunctionNode,
    JsonExpr,
    LengthOfNode,
    LiteralNode,
    RefModNode,
    expr_from_dict,
    expr_to_dict,
)


def test_expr_from_dict_literal() -> None:
    assert expr_from_dict({"kind": "lit", "value": "5"}) == LiteralNode(value="5")


def test_expr_from_dict_field_ref_with_subscripts() -> None:
    node = expr_from_dict(
        {
            "kind": "ref",
            "name": "WS-TABLE",
            "subscripts": [{"kind": "lit", "value": "1"}],
        }
    )
    assert node == FieldRefNode(name="WS-TABLE", subscripts=(LiteralNode(value="1"),))


def test_expr_from_dict_ref_mod() -> None:
    node = expr_from_dict(
        {
            "kind": "ref",
            "name": "WS-FIELD",
            "ref_mod_start": {"kind": "lit", "value": "2"},
            "ref_mod_length": {"kind": "lit", "value": "3"},
        }
    )
    assert node == RefModNode(
        name="WS-FIELD",
        ref_mod_start=LiteralNode(value="2"),
        ref_mod_length=LiteralNode(value="3"),
    )


def test_expr_from_dict_binop() -> None:
    node = expr_from_dict(
        {
            "kind": "binop",
            "op": "+",
            "left": {"kind": "lit", "value": "1"},
            "right": {"kind": "ref", "name": "WS-A"},
        }
    )
    assert node == BinOpNode(
        op="+", left=LiteralNode(value="1"), right=FieldRefNode(name="WS-A")
    )


def test_expr_from_dict_neg_folds_into_binop_multiply_by_negative_one() -> None:
    node = expr_from_dict({"kind": "neg", "expr": {"kind": "ref", "name": "WS-A"}})
    assert node == BinOpNode(
        op="*", left=LiteralNode(value="-1"), right=FieldRefNode(name="WS-A")
    )


def test_expr_from_dict_function() -> None:
    node = expr_from_dict(
        {
            "kind": "function",
            "name": "UPPER-CASE",
            "args": [{"kind": "ref", "name": "WS-IN"}],
        }
    )
    assert node == FunctionNode(name="UPPER-CASE", args=(FieldRefNode(name="WS-IN"),))


def test_expr_from_dict_figurative_constant() -> None:
    """COMPUTE WS-PCT = ZEROES is legal COBOL, and the bridge serializes that
    operand as its own node kind. Rejecting the kind cost the whole program: the
    ValueError escaped CobolASG.from_dict, so a member lost every fact it had
    over one figurative operand.
    """
    node = expr_from_dict({"kind": "figurative", "value": "ZEROS"})
    assert node == FigurativeNode(value="ZEROS")


def test_expr_from_dict_length_of_special_register() -> None:
    """LENGTH OF WS-A is a compile-time byte count, not a read of the field.

    The bridge emits it as an arithmetic operand (``serializeBasisCtx``), so
    COMPUTE WS-N = LENGTH OF WS-A + 1 reaches here.
    """
    node = expr_from_dict(
        {
            "kind": "binop",
            "op": "+",
            "left": {"kind": "length_of", "name": "WS-A"},
            "right": {"kind": "lit", "value": "1"},
        }
    )
    assert node == BinOpNode(
        op="+", left=LengthOfNode(name="WS-A"), right=LiteralNode(value="1")
    )


def test_expr_from_dict_dfhresp_condition() -> None:
    """DFHRESP(NORMAL) is a CICS response code the translator substitutes for a
    number; the bridge keeps the condition name rather than the number, because
    the number is release-dependent.
    """
    node = expr_from_dict({"kind": "dfhresp", "condition": "NORMAL"})
    assert node == DfhRespNode(condition="NORMAL")


def test_expr_from_dict_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="Unknown expression node kind"):
        expr_from_dict({"kind": "bogus"})


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "lit", "value": "5"},
        {"kind": "ref", "name": "WS-A"},
        {"kind": "ref", "name": "WS-A", "subscripts": [{"kind": "lit", "value": "1"}]},
        {
            "kind": "binop",
            "op": "+",
            "left": {"kind": "lit", "value": "1"},
            "right": {"kind": "ref", "name": "WS-A"},
        },
        {"kind": "function", "name": "TRIM", "args": [{"kind": "ref", "name": "WS-A"}]},
        {"kind": "figurative", "value": "SPACES"},
        {"kind": "length_of", "name": "WS-A"},
        {"kind": "dfhresp", "condition": "NOTFND"},
    ],
)
def test_expr_from_dict_and_expr_to_dict_round_trip(data: JsonExpr) -> None:
    assert expr_to_dict(expr_from_dict(data)) == data


def test_expr_to_dict_ref_mod_includes_start_and_length() -> None:
    node = RefModNode(
        name="WS-FIELD",
        ref_mod_start=LiteralNode(value="2"),
        ref_mod_length=LiteralNode(value="3"),
    )
    assert expr_to_dict(node) == {
        "kind": "ref",
        "name": "WS-FIELD",
        "ref_mod_start": {"kind": "lit", "value": "2"},
        "ref_mod_length": {"kind": "lit", "value": "3"},
    }
