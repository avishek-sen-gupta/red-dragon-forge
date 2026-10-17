"""The text of a PERFORM spec's operand: the name or literal it holds, upper-cased."""

from __future__ import annotations

from cobble.dataflow.srccfg.expression_text import expression_text
from cobol_asg.cobol_expression import ExprNode


def spec_text(value: ExprNode) -> str:
    return expression_text(value).upper()
