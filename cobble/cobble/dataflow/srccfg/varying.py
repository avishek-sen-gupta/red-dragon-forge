"""A PERFORM spec's operand: its text, the fields the CFG says it reads, and the operand
its synthetic MOVE or ADD reads."""

from __future__ import annotations

from cobble.dataflow.srccfg.expression_text import expression_text
from cobol_asg.cobol_expression import ExprNode, FieldRefNode, LengthOfNode
from cobol_asg.ref_mod import RefModLengthOf, RefModOperand


def spec_text(value: ExprNode) -> str:
    return expression_text(value).upper()


def spec_reads(value: ExprNode) -> tuple[str, ...]:
    """The operand's text, or nothing for LENGTH OF: a compile-time constant, not a
    field of that name."""
    return () if isinstance(value, LengthOfNode) else (spec_text(value),)


def spec_operand(value: ExprNode) -> RefModOperand:
    """The operand as the fixpoint reads it: a field reference keeps its qualifiers and
    subscripts, LENGTH OF stays a constant, and a literal stays its text."""
    match value:
        case FieldRefNode():
            return RefModOperand(
                name=value.name.upper(),
                qualifiers=value.qualifiers,
                subscripts=value.subscripts,
            )
        case LengthOfNode():
            return RefModOperand(
                name="",
                length_of=RefModLengthOf(name=value.name, qualifiers=value.qualifiers),
            )
        case _:
            return RefModOperand(name=spec_text(value))
