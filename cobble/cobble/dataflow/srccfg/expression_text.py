"""The text an ASG expression is read as: a field's name, a literal's value, an operator joining them."""

from __future__ import annotations

from cobble.dataflow.srccfg.synthetic import dfhresp_operand
from cobol_asg.cobol_expression import (
    BinOpNode,
    DfhRespNode,
    ExprNode,
    FieldRefNode,
    FigurativeNode,
    FunctionNode,
    LengthOfNode,
    LiteralNode,
    RefModNode,
)

LENGTH_OF = "LENGTH OF"
FUNCTION = "FUNCTION"


def expression_text(node: ExprNode) -> str:
    match node:
        case FieldRefNode() | RefModNode():
            return node.name
        case LiteralNode() | FigurativeNode():
            return node.value
        case _:
            return _compound_text(node)


def _compound_text(node: ExprNode) -> str:
    match node:
        case BinOpNode(op=op, left=left, right=right):
            return f"{expression_text(left)} {op} {expression_text(right)}"
        case DfhRespNode(condition=condition):
            return dfhresp_operand(condition)
        case _:
            return _named_text(node)


def _named_text(node: ExprNode) -> str:
    match node:
        case FunctionNode():
            return f"{FUNCTION} {node.name}"
        case LengthOfNode():
            return f"{LENGTH_OF} {node.name}"
        case _:
            return ""
