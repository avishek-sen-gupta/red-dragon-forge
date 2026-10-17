"""ASG condition dicts to a tree of atoms.

Only reading happens here. AND/OR/NOT stay as nodes; turning them into TEST
chains is desugar.py's job, and NOT in particular is implemented there as an edge
swap, which is why it must survive as a node rather than being folded into the
operator now -- an 88 name and a class test have no operator to fold into.

A shape this module does not recognise yields UNRESOLVED rather than raising. The
leaf still exists, so no path is silently removed; what is lost is the parts, and
that loss is visible in every report because ``resolved`` is False.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import reduce
from itertools import accumulate, repeat, takewhile

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom
from cobble.dataflow.srccfg.expression_text import expression_text
from cobble.dataflow.srccfg.synthetic import dfhresp_operand
from cobol_asg.any_object import AnyObject
from cobol_asg.evaluate_selection import SelectionObject, SelectionSubject
from cobol_asg.expression_subject import ExpressionSubject
from cobol_asg.range_object import RangeObject
from cobol_asg.selection_condition import SelectionCondition
from cobol_asg.truth_value import TruthValue
from cobol_asg.value_object import ValueObject

EIGHTY_EIGHT = "88"
CLASS = "CLASS"

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


ConditionData = Mapping | str | None
"""What the ASG hands over for a condition or an operand: ``IfStatement`` and
``SelectionCondition`` type it ``dict``, a relation operand may be a name, and a
missing key reads as None."""


def read_condition(raw: ConditionData) -> Cond:
    match raw:
        case str():
            return _named(raw)
        case Mapping():
            return _read_mapping(raw)
        case _:
            return UNRESOLVED


def _read_mapping(raw: Mapping) -> Cond:
    if _is_combination(raw):
        return _combined(raw)
    return _wrap(raw, _body(raw))


def _wrap(raw: Mapping, inner: Cond) -> Cond:
    return Not(inner=inner) if raw.get("not") else inner


def _body(raw: Mapping) -> Cond:
    """The first shape the dict carries, in the order the bridge can nest them."""
    return next(
        (read(raw) for applies, read in _BODY_SHAPES if applies(raw)), UNRESOLVED
    )


def _is_combination(raw: Mapping) -> bool:
    return "op" in raw and "left" in raw


_BODY_SHAPES = (
    (lambda raw: "relation" in raw, lambda raw: _relation(raw["relation"])),
    (lambda raw: "condition" in raw, lambda raw: read_condition(raw["condition"])),
    (
        lambda raw: "condition_name" in raw,
        lambda raw: _named(str(raw["condition_name"])),
    ),
    (lambda raw: "class" in raw, lambda raw: _class_test(raw)),
)


_COMBINATIONS = {"AND": And, "OR": Or}


def _combined(raw: Mapping) -> Cond:
    """A chain of combinations, read down its left side and folded back up.

    The bridge nests ``A OR B OR C`` on the left, one level per operand, so a
    recursive read costs a stack frame per operand and a long chain overflows.
    """
    spine = _left_spine(raw)
    return reduce(_linked, reversed(spine), read_condition(spine[-1]["left"]))


def _left_spine(raw: Mapping) -> tuple[Mapping, ...]:
    """The combinations down the left side, outermost first."""
    lefts = accumulate(repeat(None), lambda node, _: node["left"], initial=raw)
    return tuple(takewhile(_is_combination_node, lefts))


def _is_combination_node(node: ConditionData) -> bool:
    return isinstance(node, Mapping) and _is_combination(node)


def _linked(left: Cond, link: Mapping) -> Cond:
    combination = _COMBINATIONS.get(str(link["op"]))
    if not combination:
        return _wrap(link, UNRESOLVED)
    return _wrap(link, combination(left=left, right=read_condition(link["right"])))


def _relation(raw: ConditionData) -> Cond:
    if not isinstance(raw, Mapping):
        return UNRESOLVED
    left = _operand(raw.get("left"))
    right = _operand(raw.get("right"))
    op = str(raw.get("op", ""))
    if not op or not left:
        return UNRESOLVED
    return Atom(text=f"{left} {op} {right}", left=left, op=op, right=right)


def _operand(raw: ConditionData) -> str:
    match raw:
        case str():
            return raw
        case Mapping():
            return _operand_of_kind(raw)
        case _:
            return ""


def _operand_of_kind(raw: Mapping) -> str:
    read = _OPERAND_KINDS.get(str(raw.get("kind", "")))
    return read(raw) if read else ""


# A figurative constant is a literal that happens to have a name. Reading it as one
# keeps `IF X = SPACES OR LOW-VALUES` two distinguishable predicates rather than two
# copies of "X == "; is_literal already covers these names, so nothing downstream
# mistakes SPACES for a field.
_OPERAND_KINDS = {
    "ref": lambda raw: str(raw.get("name", "")),
    "lit": lambda raw: str(raw.get("value", "")),
    "figurative": lambda raw: str(raw.get("value", "")),
    "dfhresp": lambda raw: dfhresp_operand(str(raw.get("condition", ""))),
}


def _named(name: str) -> Cond:
    return Atom(text=name, left=name, op=EIGHTY_EIGHT) if name else UNRESOLVED


def _class_test(raw: Mapping) -> Cond:
    operand = _operand(raw.get("operand"))
    class_name = str(raw.get("class", ""))
    if not operand:
        return UNRESOLVED
    return class_atom(operand, class_name)


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
        return Atom(
            text=f"NOT {atom.text}", left=atom.left, op=atom.op, right=atom.right
        )
    return Atom(
        text=f"{atom.left} {flipped} {atom.right}",
        left=atom.left,
        op=flipped,
        right=atom.right,
    )


IN = "IN"
RANGE = "RANGE"

VALUE_OPS = frozenset({CLASS, EIGHTY_EIGHT, IN, RANGE})
"""The operators whose ``right`` is a value rather than a second operand.

``IS NUMERIC`` puts a class name there, an 88 resolution puts its list of VALUEs
there, a THRU range puts ``lo THRU hi``. A consumer collecting the fields a
condition depends on must read ``left`` only for these, because ``NUMERIC`` and
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


def _signature(entry: EightyEight) -> tuple[str, str, str]:
    op, right = _op_and_right(entry)
    return (entry.parent, op, right)


def _walk_fields(fields) -> tuple[EightyEight, ...]:
    return tuple(
        entry
        for cobol_field in fields
        for entry in (*_entries(cobol_field), *_walk_fields(cobol_field.children))
    )


def _entries(cobol_field) -> tuple[EightyEight, ...]:
    return tuple(
        EightyEight(
            name=condition.name.upper(),
            parent=cobol_field.name.upper(),
            values=tuple(v.from_val for v in condition.values if not v.is_range),
            ranges=tuple(
                (v.from_val, v.to_val) for v in condition.values if v.is_range
            ),
        )
        for condition in cobol_field.conditions
    )


def resolve_atom(atom: Atom, index: Mapping[str, EightyEight]) -> Atom:
    """Rewrite an 88-name atom as a predicate on its parent field.

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
    return _from_entry(atom.text, entry)


def _from_entry(name: str, entry: EightyEight) -> Atom:
    op, right = _op_and_right(entry)
    if not op:
        return Atom(text=name, left=entry.parent, op=EIGHTY_EIGHT)
    return Atom(
        text=f"{name} ({entry.parent} {op} {right})",
        left=entry.parent,
        op=op,
        right=right,
    )


def _op_and_right(entry: EightyEight) -> tuple[str, str]:
    """A mixed 88 has no single operator, so every alternative is an IN member."""
    alternatives = (*entry.values, *_render_ranges(entry.ranges))
    return next(
        (
            shape
            for applies, shape in _eighty_eight_shapes(entry, alternatives)
            if applies
        ),
        ("", ""),
    )


def _eighty_eight_shapes(
    entry: EightyEight, alternatives: tuple[str, ...]
) -> tuple[tuple[bool, tuple[str, str]], ...]:
    return (
        (bool(entry.ranges and entry.values), (IN, " ".join(alternatives))),
        (bool(entry.ranges), (RANGE, " ".join(alternatives))),
        (len(entry.values) == 1, ("==", alternatives[0] if alternatives else "")),
        (bool(entry.values), (IN, " ".join(alternatives))),
    )


def _render_ranges(ranges: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(f"{lo} THRU {hi}" for lo, hi in ranges)


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
            return _compared(expression_text(expr), *_bounds(selection))
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


def _unresolved_name(selection: ValueObject | RangeObject) -> Cond:
    match selection:
        case ValueObject(value=value):
            return _named(expression_text(value))
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


def _compared(subject: str, value: str, thru: str) -> Atom:
    if thru:
        return Atom(
            text=f"{subject} = {value} THRU {thru}",
            left=subject,
            op=RANGE,
            right=f"{value} THRU {thru}",
        )
    return Atom(text=f"{subject} == {value}", left=subject, op="==", right=value)
