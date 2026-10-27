"""Declarations for the field names a program uses but never declares, as when a
copybook is missing. A name none of whose qualifiers is declared becomes nominal
ten-byte text in a WORKING-STORAGE record of its own, under its qualifiers, and a
table where its references are subscripted. A name whose outer qualifiers are
declared is grafted under the innermost of them as a view of all its bytes -- an
over-approximation, since nothing says which of them it holds. Downstream nothing
knows the name was not declared."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace
from functools import reduce
from itertools import groupby

from cobble.asg_walk import procedure_statements
from cobble.dataflow.fields.extent import CellIndex, operand_extents
from cobble.dataflow.fields.program_layout import program_layout
from cobble.dataflow.srccfg.literals import is_literal
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_expression import FieldRefNode, RefModNode
from cobol_asg.cobol_field import CobolField
from cobol_asg.ref_mod import RefModOperand

WIDTH = 10
ROWS = 10
UNKNOWN = "unknown-name"
GROUP_STEP = 5

_Path = tuple[str, ...]
_Named = tuple[_Path, int]


def _operand(found: RefModOperand | FieldRefNode | RefModNode) -> RefModOperand:
    if isinstance(found, RefModOperand):
        return found
    return RefModOperand(
        name=found.name, qualifiers=found.qualifiers, subscripts=found.subscripts
    )


def _references(asg: CobolASG) -> Iterator[RefModOperand]:
    return (
        _operand(found)
        for found in procedure_statements(
            asg, (RefModOperand, FieldRefNode, RefModNode)
        )
    )


def _resolves(path: _Path, index: CellIndex) -> bool:
    return bool(index.cells_named(path[-1], tuple(reversed(path[:-1])), 0))


def _anchor(path: _Path, index: CellIndex) -> int:
    """How many of the path's outer names are declared, read outermost first."""
    return next(
        (
            depth
            for depth in range(len(path) - 1, 0, -1)
            if _resolves(path[:depth], index)
        ),
        0,
    )


def undeclared_names(asg: CobolASG, index: CellIndex) -> tuple[_Named, ...]:
    """Every undeclared reference's path, outermost qualifier first, with the most
    subscripts any reference to it carries. A literal is not a reference; a name
    declared elsewhere is left alone, since a second declaration would make its other
    references ambiguous."""
    found = sorted(
        {
            (path, len(operand.subscripts))
            for operand in _references(asg)
            if not is_literal(operand.name)
            and operand_extents(operand, index).reason == UNKNOWN
            for path in (
                tuple(
                    name.upper()
                    for name in (*reversed(operand.qualifiers), operand.name)
                ),
            )
            if not (len(path) > 1 and index.cells_named(path[-1], (), 0))
        }
    )
    return tuple(
        (path, max(arity for _, arity in group))
        for path, group in groupby(found, lambda named: named[0])
    )


def _rows(names: Iterable[_Named], depth: int) -> int:
    """A table when some name at or under this level needs more subscripts than the
    levels below this one can supply."""
    return ROWS if any(arity > len(path) - 1 - depth for path, arity in names) else 0


def _members(names: Iterable[_Named], level: int, depth: int) -> tuple[CobolField, ...]:
    """One field per name at ``depth``, laid end to end."""
    grouped = tuple(
        (name, tuple(group))
        for name, group in groupby(sorted(names), lambda named: named[0][depth])
    )
    sized = tuple(_member(name, group, level, depth) for name, group in grouped)
    offsets = tuple(sum(width for _, width in sized[:n]) for n in range(len(sized)))
    return tuple(
        replace(field, offset=offset)
        for (field, _), offset in zip(sized, offsets, strict=True)
    )


def _member(
    name: str, group: Sequence[_Named], level: int, depth: int
) -> tuple[CobolField, int]:
    below = tuple(named for named in group if len(named[0]) > depth + 1)
    children = _members(below, GROUP_STEP * (depth + 1), depth + 1)
    occurs = _rows(group, depth)
    unit = _width(below, depth + 1) if children else WIDTH
    field = CobolField(
        name=name,
        level=level,
        pic="" if children else f"X({WIDTH})",
        usage="DISPLAY",
        offset=0,
        occurs=occurs,
        children=list(children),
    )
    return field, unit * max(occurs, 1)


def _width(names: Sequence[_Named], depth: int) -> int:
    return sum(
        _member(name, tuple(group), 0, depth)[1]
        for name, group in groupby(sorted(names), lambda named: named[0][depth])
    )


def _chain(names: _Path, level: int, width: int, occurs: int) -> CobolField:
    """``names`` nested outermost first, each as wide as the one holding it; the last
    one a table of ``occurs`` when it needs one."""
    head, rest = names[0], names[1:]
    inner = (_chain(rest, level + 1, width, occurs),) if rest else ()
    return CobolField(
        name=head,
        level=level,
        pic="" if inner else f"X({width})",
        usage="DISPLAY",
        offset=0,
        occurs=0 if inner else occurs,
        children=list(inner),
    )


def _grafted(field: CobolField, anchor: _Path, view: CobolField) -> CobolField:
    """``field`` with ``view`` under the field ``anchor`` names, qualifiers in order
    with any levels between them; the view redefines that field's first child, so it
    spans its bytes and allocates none."""
    rest = anchor[1:] if field.name.upper() == anchor[0] else anchor
    if rest:
        return replace(
            field, children=[_grafted(kid, rest, view) for kid in field.children]
        )
    return _viewed(field, view)


def _viewed(field: CobolField, view: CobolField) -> CobolField:
    if not field.children:
        return field
    first = field.children[0]
    placed = replace(view, level=first.level, redefines=first.name)
    return replace(field, children=[*field.children, placed])


def _grafted_by(
    roots: Sequence[CobolField], grafts: Sequence[tuple[_Path, CobolField]]
) -> list[CobolField]:
    return [
        reduce(lambda grown, graft: _grafted(grown, *graft), grafts, root)
        for root in roots
    ]


def _graft_all(asg: CobolASG, grafts: Sequence[tuple[_Path, CobolField]]) -> CobolASG:
    return replace(
        asg,
        data_fields=_grafted_by(asg.data_fields, grafts),
        linkage_fields=_grafted_by(asg.linkage_fields, grafts),
        local_storage_fields=_grafted_by(asg.local_storage_fields, grafts),
        file_fields=_grafted_by(asg.file_fields, grafts),
    )


def _view(named: _Named, depth: int, index: CellIndex) -> tuple[_Path, CobolField]:
    """The view under the declared anchor: as wide as the anchor, and a table when its
    references carry more subscripts than the anchor's own tables supply."""
    path, arity = named
    anchor = path[:depth]
    cell, *_ = index.cells_named(anchor[-1], tuple(reversed(anchor[:-1])), 0)
    occurs = ROWS if arity > len(cell.index) else 0
    return anchor, _chain(path[depth:], GROUP_STEP, cell.length, occurs)


def with_undeclared(asg: CobolASG) -> tuple[CobolASG, tuple[_Path, ...]]:
    """The program with every undeclared name declared, and their paths."""
    index = program_layout(asg).index
    names = undeclared_names(asg, index)
    anchored = tuple((named, _anchor(named[0], index)) for named in names)
    grafts = tuple(_view(named, depth, index) for named, depth in anchored if depth)
    records = _members((named for named, depth in anchored if not depth), 1, 0)
    grown = _graft_all(asg, grafts)
    return (
        replace(grown, data_fields=[*grown.data_fields, *records]),
        tuple(path for path, _ in names),
    )
