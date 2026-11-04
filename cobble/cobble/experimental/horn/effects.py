"""The assignments stage 1 encodes exactly: SET of a single-valued 88, and MOVE of a literal or figurative."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cobble.dataflow.srccfg.conditions import EightyEight
from cobble.experimental.horn.atoms import FIGURATIVES, quoted, unquoted
from cobble.experimental.horn.tracked import Tracked
from cobol_asg.cobol_statements import CobolStatementType, MoveStatement, SetStatement
from cobol_asg.operand_kind import OperandKind
from cobol_asg.ref_mod import RefModOperand
from cobol_asg.set_operand import SetOperand

TRUE = "TRUE"


@dataclass(frozen=True)
class Exact:
    field: str
    value: str


def filled(value: str, length: int) -> tuple[str, ...]:
    if quoted(value):
        return (unquoted(value)[:length].ljust(length),)
    if value in FIGURATIVES:
        return (FIGURATIVES[value] * length,)
    return ()


def _plain(target: RefModOperand, fields: Mapping[str, Tracked]) -> bool:
    return (
        target.name in fields
        and not target.is_reference_modified
        and not target.subscripts
    )


def _moved(move: MoveStatement, fields: Mapping[str, Tracked]) -> tuple[Exact, ...]:
    source = move.source
    if not isinstance(source, RefModOperand) or source.kind not in (
        OperandKind.LIT,
        OperandKind.FIGURATIVE,
    ):
        return ()
    if source.is_reference_modified:
        return ()
    return tuple(
        Exact(target.name, value)
        for target in move.targets
        if _plain(target, fields)
        for value in filled(source.name, fields[target.name].length)
    )


def _single(condition: EightyEight, fields: Mapping[str, Tracked]) -> bool:
    return (
        condition.parent in fields
        and len(condition.values) == 1
        and not condition.ranges
    )


def _true(set_: SetStatement) -> bool:
    return (
        set_.set_type == "TO"
        and len(set_.values) == 1
        and set_.values[0].kind is OperandKind.LIT
        and set_.values[0].value.upper() == TRUE
    )


def _condition(
    target: SetOperand, conditions: Mapping[str, EightyEight]
) -> tuple[EightyEight, ...]:
    name = target.name.upper()
    named = target.kind is OperandKind.REF and not target.subscripts
    return (conditions[name],) if named and name in conditions else ()


def _set(
    set_: SetStatement,
    conditions: Mapping[str, EightyEight],
    fields: Mapping[str, Tracked],
) -> tuple[Exact, ...]:
    if not _true(set_):
        return ()
    return tuple(
        Exact(condition.parent, value)
        for target in set_.targets
        for condition in _condition(target, conditions)
        if _single(condition, fields)
        for value in filled(condition.values[0], fields[condition.parent].length)
    )


def exact_writes(
    statement: CobolStatementType,
    conditions: Mapping[str, EightyEight],
    fields: Sequence[Tracked],
) -> tuple[Exact, ...]:
    by_name = {field.name: field for field in fields}
    if isinstance(statement, MoveStatement):
        return _moved(statement, by_name)
    if isinstance(statement, SetStatement):
        return _set(statement, conditions, by_name)
    return ()
