"""What CICS program control decides: the field an XCTL names its target in, the paragraphs a PGMIDERR goes to, and the commands that never raise it."""

from cics.statements import CicsOperand, ExecCicsStatement
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.storage import Storage

XCTL = "XCTL"
PROGRAM_OPTION = "PROGRAM"
HANDLE_CONDITION = "HANDLE CONDITION"
PGMIDERR = "PGMIDERR"
NO_PGMIDERR = frozenset({"RETURN", "SEND MAP"})


def program_field(program: Program, node: str) -> str:
    """The one alphanumeric field an XCTL at ``node`` names its target in, or
    nothing: a literal target, another command, or a field that is not one item."""
    statement = program.statements.get(node)
    if not isinstance(statement, ExecCicsStatement) or statement.verb != XCTL:
        return ""
    operand = statement.options.get(PROGRAM_OPTION)
    if not isinstance(operand, CicsOperand) or operand.is_literal:
        return ""
    return operand.text if Storage(program.index, ()).field(operand.text) else ""


def pgmiderr_handlers(program: Program) -> frozenset[str]:
    """The paragraphs HANDLE CONDITION arms for PGMIDERR and for no other
    condition."""
    armed = tuple(
        (name.upper(), operand.text.upper())
        for statement in program.statements.values()
        if isinstance(statement, ExecCicsStatement)
        and statement.verb == HANDLE_CONDITION
        for name, operand in statement.options.items()
        if isinstance(operand, CicsOperand)
    )
    shared = frozenset(label for name, label in armed if name != PGMIDERR)
    return frozenset(label for name, label in armed if name == PGMIDERR) - shared


def never_pgmiderr(program: Program, node: str) -> bool:
    """IBM's condition lists for RETURN and SEND MAP have no PGMIDERR."""
    statement = program.statements.get(node)
    return isinstance(statement, ExecCicsStatement) and statement.verb in NO_PGMIDERR
