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

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom
from cobble.dataflow.srccfg.synthetic import dfhresp_operand

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


def read_condition(raw: object) -> Cond:
    if isinstance(raw, str):
        return _named(raw)
    if not isinstance(raw, Mapping):
        return UNRESOLVED
    return _wrap(raw, _body(raw))


def _wrap(raw: Mapping, inner: Cond) -> Cond:
    return Not(inner=inner) if raw.get("not") else inner


def _body(raw: Mapping) -> Cond:
    if "op" in raw and "left" in raw:
        return _combine(str(raw["op"]), raw["left"], raw["right"])
    if "relation" in raw:
        return _relation(raw["relation"])
    if "condition" in raw:
        return read_condition(raw["condition"])
    if "condition_name" in raw:
        return _named(str(raw["condition_name"]))
    if "class" in raw:
        return _class_test(raw)
    return UNRESOLVED


def _combine(op: str, left: object, right: object) -> Cond:
    read = (read_condition(left), read_condition(right))
    if op == "AND":
        return And(left=read[0], right=read[1])
    if op == "OR":
        return Or(left=read[0], right=read[1])
    return UNRESOLVED


def _relation(raw: object) -> Cond:
    if not isinstance(raw, Mapping):
        return UNRESOLVED
    left = _operand(raw.get("left"))
    right = _operand(raw.get("right"))
    op = str(raw.get("op", ""))
    if not op or not left:
        return UNRESOLVED
    return Atom(text=f"{left} {op} {right}", left=left, op=op, right=right)


def _operand(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, Mapping):
        return ""
    kind = raw.get("kind")
    if kind == "ref":
        return str(raw.get("name", ""))
    if kind == "lit":
        return str(raw.get("value", ""))
    if kind == "dfhresp":
        return dfhresp_operand(str(raw.get("condition", "")))
    return ""


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
    if entry.ranges and entry.values:
        # A mixed 88 has no single operator; list every alternative as IN members.
        alternatives = (*entry.values, *_render_ranges(entry.ranges))
        return (IN, " ".join(alternatives))
    if entry.ranges:
        return (RANGE, " ".join(_render_ranges(entry.ranges)))
    if len(entry.values) == 1:
        return ("==", entry.values[0])
    if entry.values:
        return (IN, " ".join(entry.values))
    return ("", "")


def _render_ranges(ranges: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(f"{lo} THRU {hi}" for lo, hi in ranges)


ALWAYS = Atom(text="ANY", left="", op="", right="")
_WHEN_ANY = ("ANY", "OTHER", "")


def read_when_condition(raw: object, thru: str = "") -> Cond:
    """A WHEN branch's condition.

    EVALUATE TRUE gives a structured dict, and that path is read_condition's. The
    other form arrives as text the ASG has already prefixed with the subject --
    "WS-X = 'A'" -- and the parts have to be recovered from it, because without
    them the subject is not a dependency of anything in the branch.
    """
    if not isinstance(raw, str):
        return read_condition(raw)
    text = raw.strip()
    if text.upper() in _WHEN_ANY:
        return ALWAYS
    return _from_when_text(text, thru)


def _from_when_text(text: str, thru: str) -> Cond:
    subject, _, value = text.partition(" = ")
    if not value:
        return _named(text)
    if thru:
        return Atom(
            text=f"{subject} = {value} THRU {thru}",
            left=subject,
            op=RANGE,
            right=f"{value} THRU {thru}",
        )
    return Atom(text=f"{subject} == {value}", left=subject, op="==", right=value)
