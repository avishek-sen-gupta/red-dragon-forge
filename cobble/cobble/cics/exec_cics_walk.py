"""Every EXEC CICS statement under an ASG, in source order, by one walk linear in the ASG's size."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import TYPE_CHECKING, TypeAlias

from cics.statements import ExecCicsStatement

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

_Node: TypeAlias = (
    "DataclassInstance | list[_Node] | tuple[_Node, ...] | dict[str, _Node]"
)


def _is_node(value: _Node | str | int | float | bool | None) -> bool:
    return isinstance(value, (list, tuple, dict)) or (
        dataclasses.is_dataclass(value) and not isinstance(value, type)
    )


def _children(node: _Node) -> Iterator[_Node]:
    """What a walk descends into, in source order: a dataclass's field values, a
    sequence's items, a dict's values -- keeping only those that can hold more."""
    if isinstance(node, dict):
        return (value for value in node.values() if _is_node(value))
    if isinstance(node, (list, tuple)):
        return (item for item in node if _is_node(item))
    fields = (getattr(node, f.name) for f in dataclasses.fields(node))
    return (value for value in fields if _is_node(value))


def exec_cics_statements(root: DataclassInstance) -> tuple[ExecCicsStatement, ...]:
    seen: set[int] = set()
    stack: list[_Node] = [root]
    found: list[ExecCicsStatement] = []
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, ExecCicsStatement):
            found.append(node)
            continue
        stack.extend(reversed(tuple(_children(node))))
    return tuple(found)
