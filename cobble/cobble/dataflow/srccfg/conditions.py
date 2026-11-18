"""ASG conditions to a tree of atoms.

Only reading happens here. AND/OR/NOT stay as nodes; turning them into TEST
chains is desugar.py's job, and NOT in particular is implemented there as an edge
swap, which is why it must survive as a node rather than being folded into the
operator now -- an 88 name and a class test have no operator to fold into.

A test this module cannot take apart yields UNRESOLVED rather than raising. The
leaf still exists, so no path is silently removed; what is lost is the parts, and
that loss is visible in every report because ``resolved`` is False.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import reduce, singledispatch

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom
from cobble.dataflow.srccfg.declared_condition import DeclaredCondition
from cobble.dataflow.srccfg.expression_text import expression_text
from cobble.dataflow.srccfg.synthetic import dfhresp_operand
from cobol_asg.any_object import AnyObject
from cobol_asg.cobol_expression import (
    AddressOfNode,
    AllLiteralNode,
    DfhRespNode,
    ExprNode,
    FieldRefNode,
    FigurativeNode,
    LiteralNode,
    RefModNode,
)
from cobol_asg.condition import (
    ClassTest,
    Combination,
    Condition,
    ConditionNameTest,
    Connective,
    Parenthesised,
    RelationTest,
)
from cobol_asg.condition_name import ConditionValue
from cobol_asg.evaluate_selection import SelectionObject, SelectionSubject
from cobol_asg.expression_subject import ExpressionSubject
from cobol_asg.operand_kind import OperandKind
from cobol_asg.range_object import RangeObject
from cobol_asg.ref_mod import RefModOperand
from cobol_asg.selection_condition import SelectionCondition
from cobol_asg.truth_value import TruthValue
from cobol_asg.value_object import ValueObject

EIGHTY_EIGHT = "88"
CLASS = "CLASS"

_QUOTE = "'"
_OPPOSITE = {"==": "!=", "!=": "==", ">": "<=", "<=": ">", "<": ">=", ">=": "<"}


@dataclass(frozen=True)
class And:
    left: Cond
    right: Cond


@dataclass(frozen=True)
class Or:
    left: Cond
    right: Cond


@dataclass(frozen=True)
class Not:
    inner: Cond


Cond = Atom | And | Or | Not


def read_condition(condition: Condition) -> Cond:
    if isinstance(condition, Combination):
        return _combined(condition)
    return _negated_if(condition.negated, _test(condition))


@singledispatch
def _test(condition: Condition) -> Cond:
    """The test without its NOT. A user class, a sign test and text the bridge did
    not structure have no parts to read."""
    return UNRESOLVED


@_test.register
def _(condition: RelationTest) -> Cond:
    return _relation(condition)


@_test.register
def _(condition: Parenthesised) -> Cond:
    return read_condition(condition.inner)


@_test.register
def _(condition: ConditionNameTest) -> Cond:
    return _named(condition.name, not condition.subscripts)


@_test.register
def _(condition: ClassTest) -> Cond:
    return _class_test(condition)


_COMBINATIONS = {Connective.AND: And, Connective.OR: Or}


def _combined(condition: Combination) -> Cond:
    """The operands folded on the left, as the bridge nested them."""
    join = _COMBINATIONS[condition.connective]
    return reduce(
        lambda left, operand: join(left=left, right=read_condition(operand)),
        condition.operands[1:],
        read_condition(condition.operands[0]),
    )


def _relation(condition: RelationTest) -> Cond:
    left = _operand(condition.left)
    right = _operand(condition.right)
    op = condition.operator.value
    if not left:
        return UNRESOLVED
    return Atom(
        text=f"{left} {op} {right}",
        left=left,
        op=op,
        right=right,
        plain=_whole(condition.left) and _whole(condition.right),
    )


def _whole(node: ExprNode) -> bool:
    """A relation operand that names all of its field, or a literal."""
    match node:
        case RefModNode():
            return False
        case FieldRefNode() | AddressOfNode():
            return not node.subscripts
        case _:
            return True


# A figurative constant is a literal that happens to have a name. Reading it as one
# keeps `IF X = SPACES OR LOW-VALUES` two distinguishable predicates rather than two
# copies of "X == "; is_literal already covers these names, so nothing downstream
# mistakes SPACES for a field.
@singledispatch
def _operand(node: ExprNode) -> str:
    return ""


@_operand.register
def _(node: FieldRefNode | RefModNode) -> str:
    return node.name


@_operand.register
def _(node: LiteralNode | FigurativeNode) -> str:
    return node.value


@_operand.register
def _(node: AllLiteralNode) -> str:
    return ALL


@_operand.register
def _(node: DfhRespNode) -> str:
    return dfhresp_operand(node.condition)


ALL = "ALL"


def _named(name: str, plain: bool) -> Cond:
    if not name:
        return UNRESOLVED
    return Atom(text=name, left=name, op=EIGHTY_EIGHT, plain=plain)


def _class_test(condition: ClassTest) -> Cond:
    operand = _operand(condition.operand)
    if not operand:
        return UNRESOLVED
    return class_atom(operand, condition.kind.value)


def class_atom(operand: str, class_name: str) -> Atom:
    return Atom(
        text=f"{operand} IS {class_name}", left=operand, op=CLASS, right=class_name
    )


def negate_atom(atom: Atom) -> Atom:
    """The readable form of an atom's FALSE edge.

    The graph needs no such thing -- the edge is the negation -- but a report that
    prints a path does. The parts are unchanged where there is no opposite
    operator, because the field depended on is the same either way.
    """
    if not atom.resolved:
        return atom
    flipped = _OPPOSITE.get(atom.op, "")
    if not flipped:
        return replace(atom, text=f"NOT {atom.text}")
    return replace(atom, text=f"{atom.left} {flipped} {atom.right}", op=flipped)


RANGE = "RANGE"

VALUE_OPS = frozenset({CLASS, EIGHTY_EIGHT, RANGE})
"""The operators whose ``right`` is a value rather than a second operand.

``IS NUMERIC`` puts a class name there and a THRU range puts ``lo THRU hi``. A
consumer collecting the fields a condition depends on must read ``left`` only for
these, because ``NUMERIC`` and
``1 THRU 9`` are not fields and reporting them as fields written nowhere in the
member devalues that line wherever it is true.
"""


@dataclass(frozen=True)
class EightyEight:
    """A level-88 condition name and the parent field it tests."""

    name: str
    parent: str
    values: tuple[str, ...] = ()
    ranges: tuple[tuple[str, str], ...] = ()


def condition_index(asg) -> Mapping[str, EightyEight]:
    """Every 88 name declared anywhere in the program, keyed upper-case.

    All four data sections are walked, and each is a forest -- an 88 hangs off an
    elementary item that is normally a child of an 01, so only a recursive walk
    finds them. A name declared more than once is kept only if every declaration
    yields the same resolution; ambiguous names are omitted.
    """
    roots = (
        *asg.data_fields,
        *asg.linkage_fields,
        *asg.local_storage_fields,
        *asg.file_fields,
    )
    return _deduplicate(_walk_fields(roots))


def _deduplicate(entries: tuple[EightyEight, ...]) -> Mapping[str, EightyEight]:
    grouped = _group_by_name(entries)
    return {name: group[0] for name, group in grouped.items() if _unanimous(group)}


def _group_by_name(
    entries: tuple[EightyEight, ...],
) -> Mapping[str, tuple[EightyEight, ...]]:
    names = {entry.name for entry in entries}
    return {name: tuple(e for e in entries if e.name == name) for name in names}


def _unanimous(group: tuple[EightyEight, ...]) -> bool:
    return len({_signature(e) for e in group}) == 1


def _signature(
    entry: EightyEight,
) -> tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]:
    return (entry.parent, entry.values, entry.ranges)


def _walk_fields(fields) -> tuple[EightyEight, ...]:
    return tuple(
        entry
        for cobol_field in fields
        for entry in (*_entries(cobol_field), *_walk_fields(cobol_field.children))
    )


def _shown(value: ConditionValue, characters: str) -> str:
    if value.numeric or value.figurative:
        return characters
    return _QUOTE + characters.replace(_QUOTE, _QUOTE * 2) + _QUOTE


def _entries(cobol_field) -> tuple[EightyEight, ...]:
    return tuple(
        EightyEight(
            name=condition.name.upper(),
            parent=cobol_field.name.upper(),
            values=tuple(
                _shown(v, v.from_val) for v in condition.values if not v.is_range
            ),
            ranges=tuple(
                (_shown(v, v.from_val), _shown(v, v.to_val))
                for v in condition.values
                if v.is_range
            ),
        )
        for condition in cobol_field.conditions
    )


def declared_conditions(asg) -> Mapping[str, tuple[DeclaredCondition, ...]]:
    """Every declaration of every 88 name, by upper-case name, ambiguous ones kept:
    a qualified reference chooses among them (``conditions_named``)."""
    roots = (
        *asg.data_fields,
        *asg.linkage_fields,
        *asg.local_storage_fields,
        *asg.file_fields,
    )
    found = _declared_under(roots, ())
    names = frozenset(entry.name for entry in found)
    return {name: tuple(e for e in found if e.name == name) for name in names}


def conditions_named(
    name: str,
    qualifiers: Sequence[str],
    declared: Mapping[str, tuple[DeclaredCondition, ...]],
) -> tuple[DeclaredCondition, ...]:
    """The one declaration a reference denotes, or nothing when it denotes none or
    several -- several is an ambiguous reference, which COBOL rejects."""
    found = tuple(
        entry
        for entry in declared.get(name.upper(), ())
        if entry.qualified_by(qualifiers)
    )
    return found if len(found) == 1 else ()


def _declared_under(fields, above: tuple[str, ...]) -> tuple[DeclaredCondition, ...]:
    return tuple(
        entry
        for cobol_field in fields
        for chain in ((cobol_field.name.upper(), *above),)
        for entry in (
            *_declared_at(cobol_field, chain),
            *_declared_under(cobol_field.children, chain),
        )
    )


def _declared_at(cobol_field, chain: tuple[str, ...]) -> tuple[DeclaredCondition, ...]:
    return tuple(
        DeclaredCondition(
            name=condition.name.upper(),
            enclosing=chain,
            first=_first_value(condition.values),
        )
        for condition in cobol_field.conditions
    )


def _first_value(values: Sequence[ConditionValue]) -> RefModOperand:
    if not values:
        return RefModOperand(name="")
    kind = OperandKind.FIGURATIVE if values[0].figurative else OperandKind.LIT
    return RefModOperand(name=_shown(values[0], values[0].from_val), kind=kind)


def resolve_atom(atom: Atom, index: Mapping[str, EightyEight]) -> Cond:
    """Rewrite an 88-name atom as a predicate on its parent field: one equality per
    VALUE and one range per THRU, joined by OR as a written ``X = 'A' OR X = 'B'``
    is, so lowering chains them and no consumer has to read a value list.

    The text keeps the name the code was written with, because that is what a
    reader recognises; ``left`` becomes the parent, because that is what a
    dependency query filters on. An undeclared name is left exactly as it is --
    it is still the guard that was written.
    """
    if atom.op != EIGHTY_EIGHT:
        return atom
    entry = index.get(atom.left.upper())
    if not entry:
        return atom
    return _from_entry(atom.text, entry, atom.plain)


def _from_entry(name: str, entry: EightyEight, plain: bool) -> Cond:
    alternatives = (
        *(
            _alternative(name, entry.parent, "==", value, plain)
            for value in entry.values
        ),
        *(
            _alternative(name, entry.parent, RANGE, f"{lo} THRU {hi}", plain)
            for lo, hi in entry.ranges
        ),
    )
    if not alternatives:
        return Atom(text=name, left=entry.parent, op=EIGHTY_EIGHT, plain=plain)
    return reduce(
        lambda left, right: Or(left=left, right=right),
        alternatives[1:],
        alternatives[0],
    )


def _alternative(name: str, parent: str, op: str, right: str, plain: bool) -> Cond:
    return Atom(
        text=f"{name} ({parent} {op} {right})",
        left=parent,
        op=op,
        right=right,
        plain=plain,
    )


ALWAYS = Atom(text="ANY", left="", op="", right="")


def read_when_object(selection: SelectionObject, subject: SelectionSubject) -> Cond:
    """One WHEN object, compared with the EVALUATE subject it answers.

    Under EVALUATE TRUE the object is itself a condition, and under EVALUATE FALSE
    its negation. Under an identifier or expression subject the object is a value
    or a THRU range the subject is compared with; NOT negates that comparison.
    ANY matches whatever its subject holds.
    """
    match selection:
        case AnyObject():
            return ALWAYS
        case ValueObject() | RangeObject():
            return _negated_if(selection.negated, _valued(selection, subject))
        case _:
            return _truth_object(selection, subject)


def _negated_if(negated: bool, cond: Cond) -> Cond:
    return Not(inner=cond) if negated else cond


def _negated(cond: Cond) -> Cond:
    return cond if cond == ALWAYS else Not(inner=cond)


def _valued(selection: ValueObject | RangeObject, subject: SelectionSubject) -> Cond:
    """A value under a TRUE or FALSE subject is a condition name the bridge could
    not resolve -- one declared in a copybook the parse did not have."""
    match subject:
        case ExpressionSubject(expr=expr):
            return _compared(
                expression_text(expr),
                *_bounds(selection),
                _whole_expression(expr) and _whole_bounds(selection),
            )
        case TruthValue(value=truth):
            return _against_truth(truth, _unresolved_name(selection))
        case _:
            return UNRESOLVED


def _bounds(selection: ValueObject | RangeObject) -> tuple[str, str]:
    match selection:
        case RangeObject(low=low, high=high):
            return (expression_text(low), expression_text(high))
        case ValueObject(value=value):
            return (expression_text(value), "")


def _whole_expression(node: ExprNode) -> bool:
    match node:
        case FieldRefNode(subscripts=subscripts):
            return not subscripts
        case LiteralNode() | FigurativeNode():
            return True
        case _:
            return False


def _whole_bounds(selection: ValueObject | RangeObject) -> bool:
    match selection:
        case RangeObject(low=low, high=high):
            return _whole_expression(low) and _whole_expression(high)
        case ValueObject(value=value):
            return _whole_expression(value)


def _unresolved_name(selection: ValueObject | RangeObject) -> Cond:
    match selection:
        case ValueObject(value=value):
            return _named(expression_text(value), False)
        case RangeObject():
            return UNRESOLVED


def _against_truth(truth: bool, cond: Cond) -> Cond:
    return cond if truth else _negated(cond)


def _truth_object(
    selection: TruthValue | SelectionCondition, subject: SelectionSubject
) -> Cond:
    match selection:
        case SelectionCondition(condition=condition):
            return _condition_object(read_condition(condition), subject)
        case TruthValue(value=truth):
            return _truth_answering(truth, subject)


def _condition_object(cond: Cond, subject: SelectionSubject) -> Cond:
    match subject:
        case TruthValue(value=truth):
            return _against_truth(truth, cond)
        case _:
            return cond


def _truth_answering(truth: bool, subject: SelectionSubject) -> Cond:
    match subject:
        case SelectionCondition(condition=condition):
            return _against_truth(truth, read_condition(condition))
        case _:
            return UNRESOLVED


def _compared(subject: str, value: str, thru: str, plain: bool) -> Atom:
    if thru:
        return Atom(
            text=f"{subject} = {value} THRU {thru}",
            left=subject,
            op=RANGE,
            right=f"{value} THRU {thru}",
            plain=plain,
        )
    return Atom(
        text=f"{subject} == {value}", left=subject, op="==", right=value, plain=plain
    )
