"""The node types, fields and unions the dbscheme declares, read from the type hints of the dataclasses a set of roots reaches."""

from __future__ import annotations

import dataclasses
import re
import sys
import types
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import TypeIs

from cobble.experimental.codeql.schema.shape import (
    Absent,
    Keyed,
    Located,
    NodeRef,
    Repeated,
    Scalar,
    ScalarKind,
    Shape,
)

Hint = type | types.UnionType | types.GenericAlias | typing.TypeAliasType

_SCALARS: Mapping[Hint, ScalarKind] = {
    str: ScalarKind.STRING,
    int: ScalarKind.INT,
    bool: ScalarKind.BOOLEAN,
}
_SEQUENCES = (list, tuple, Sequence)
_MAPPINGS = (dict, Mapping)
_PREFIX = "cobol_"


@dataclass(frozen=True)
class NodeField:
    """``access`` is the attribute the field is read from, or a tuple's position."""

    name: str
    shape: Shape
    access: str | int


@dataclass(frozen=True)
class NodeType:
    """``source`` is the dataclass, or for a fixed tuple the tuple's arity."""

    name: str
    table: str
    fields: tuple[NodeField, ...]
    source: type | int


@dataclass(frozen=True)
class UnionType:
    name: str
    table: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class Naming:
    """``unions`` names a union by its members; ``extended`` adds members the
    hints cannot name, such as statements a dialect parser adds. ``modules``
    resolve the forward references a hint leaves as strings."""

    location: type
    modules: tuple[types.ModuleType, ...]
    unions: Mapping[frozenset[Hint], str]
    extended: Mapping[str, tuple[type, ...]]


@dataclass(frozen=True)
class Schema:
    nodes: tuple[NodeType, ...]
    unions: tuple[UnionType, ...]

    def node_of(self, value_type: type) -> NodeType:
        return next(n for n in self.nodes if n.source is value_type)

    def node_named(self, name: str) -> NodeType:
        return next(n for n in self.nodes if n.name == name)


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def table_of(name: str) -> str:
    under = snake(name)
    return under if under.startswith(_PREFIX) else _PREFIX + under


def _is_node(hint: Hint) -> TypeIs[type]:
    return isinstance(hint, type) and dataclasses.is_dataclass(hint)


def _hints(cls: type, naming: Naming) -> Mapping[str, Hint]:
    names = reduce(
        lambda found, module: {**found, **vars(module)},
        (*naming.modules, sys.modules[cls.__module__]),
        {},
    )
    return typing.get_type_hints(cls, globalns=names)


def _arguments(hint: Hint) -> tuple[Hint, ...]:
    return tuple(a for a in typing.get_args(hint) if a is not Ellipsis)


def _is_union(hint: Hint) -> bool:
    return typing.get_origin(hint) in (typing.Union, types.UnionType)


def _members(hint: Hint, naming: Naming) -> tuple[Hint, ...]:
    parts = tuple(p for p in _arguments(hint) if p is not type(None))
    name = naming.unions.get(frozenset(parts), "")
    return (*parts, *naming.extended.get(name, ()))


def _contained(hint: Hint, naming: Naming) -> tuple[Hint, ...]:
    """The hints a field's hint is built from, the hint itself last."""
    inner = _members(hint, naming) if _is_union(hint) else _arguments(hint)
    return (*(h for part in inner for h in _contained(part, naming)), hint)


def _reached(cls: type, naming: Naming) -> tuple[type, ...]:
    return tuple(
        h
        for hint in _hints(cls, naming).values()
        for h in _contained(hint, naming)
        if _is_node(h)
    )


def reachable(roots: tuple[type, ...], naming: Naming) -> tuple[type, ...]:
    """Every dataclass the roots reach, in the order first reached."""
    return _closed(roots, (), naming)


def _closed(
    pending: tuple[type, ...], seen: tuple[type, ...], naming: Naming
) -> tuple[type, ...]:
    fresh = tuple(dict.fromkeys(c for c in pending if c not in seen))
    if not fresh:
        return seen
    found = (*seen, *fresh)
    return _closed(tuple(r for c in fresh for r in _reached(c, naming)), found, naming)


@dataclass(frozen=True)
class _Owner:
    """Where a hint sits: names an anonymous union or a fixed tuple."""

    node: str
    field: str

    def nested(self, suffix: str) -> str:
        return f"{self.node}{_pascal(self.field)}{suffix}"


def _pascal(field: str) -> str:
    return "".join(part.capitalize() for part in field.split("_"))


def _union_name(hint: Hint, naming: Naming, owner: _Owner) -> str:
    parts = tuple(p for p in _arguments(hint) if p is not type(None))
    return naming.unions.get(frozenset(parts), "") or owner.nested("Type")


def shape_of(hint: Hint, naming: Naming, owner: _Owner) -> Shape:
    if _is_union(hint):
        return _union_shape(hint, naming, owner)
    return _origin_shape(hint, naming, owner)


def _origin_shape(hint: Hint, naming: Naming, owner: _Owner) -> Shape:
    origin = typing.get_origin(hint)
    if origin in _SEQUENCES:
        return _sequence_shape(hint, naming, owner)
    if origin in _MAPPINGS:
        return Keyed(shape_of(_arguments(hint)[1], naming, owner))
    return _leaf_shape(hint, naming)


def _union_shape(hint: Hint, naming: Naming, owner: _Owner) -> Shape:
    parts = tuple(p for p in _arguments(hint) if p is not type(None))
    if len(parts) < len(_arguments(hint)):
        return Absent(_present_shape(hint, parts, naming, owner))
    return NodeRef(table_of(_union_name(hint, naming, owner)))


def _present_shape(
    hint: Hint, parts: tuple[Hint, ...], naming: Naming, owner: _Owner
) -> Shape:
    if len(parts) == 1:
        return shape_of(parts[0], naming, owner)
    return NodeRef(table_of(_union_name(hint, naming, owner)))


def _sequence_shape(hint: Hint, naming: Naming, owner: _Owner) -> Shape:
    if _is_fixed_tuple(hint):
        return NodeRef(table_of(owner.nested("Item")))
    return Repeated(shape_of(_arguments(hint)[0], naming, owner))


def _is_fixed_tuple(hint: Hint) -> bool:
    raw = typing.get_args(hint)
    return typing.get_origin(hint) is tuple and Ellipsis not in raw and len(raw) > 1


def _leaf_shape(hint: Hint, naming: Naming) -> Shape:
    if hint is naming.location:
        return Located()
    shapes = tuple(shape(hint) for applies, shape in _LEAVES if applies(hint))
    if not shapes:
        raise TypeError(f"no dbscheme shape for the type hint {hint!r}")
    return shapes[0]


def _is_enum(hint: Hint) -> bool:
    return isinstance(hint, type) and issubclass(hint, Enum)


def _is_scalar(hint: Hint) -> bool:
    return hint in _SCALARS


def _scalar(hint: Hint) -> Shape:
    return Scalar(_SCALARS[hint])


def _node_shape(hint: Hint) -> Shape:
    return NodeRef(table_of(_type_name(hint)))


_LEAVES: tuple[tuple[Callable[[Hint], bool], Callable[[Hint], Shape]], ...] = (
    (_is_enum, lambda hint: Scalar(ScalarKind.STRING)),
    (_is_scalar, _scalar),
    (_is_node, _node_shape),
)


def _fields(cls: type, naming: Naming) -> tuple[NodeField, ...]:
    return tuple(
        NodeField(name, shape_of(hint, naming, _Owner(cls.__name__, name)), name)
        for name, hint in _hints(cls, naming).items()
    )


def _tuples(hint: Hint, owner: _Owner, naming: Naming) -> tuple[NodeType, ...]:
    """The node types of the fixed tuples inside a field's hint."""
    inner = tuple(t for a in _arguments(hint) for t in _tuples(a, owner, naming))
    if not _is_fixed_tuple(hint):
        return inner
    name = owner.nested("Item")
    elements = tuple(
        NodeField(f"element{i}", shape_of(a, naming, _Owner(name, f"element{i}")), i)
        for i, a in enumerate(_arguments(hint))
    )
    return (*inner, NodeType(name, table_of(name), elements, len(elements)))


def _node_types(cls: type, naming: Naming) -> tuple[NodeType, ...]:
    own = NodeType(cls.__name__, table_of(cls.__name__), _fields(cls, naming), cls)
    tuples = tuple(
        t
        for name, hint in _hints(cls, naming).items()
        for t in _tuples(hint, _Owner(cls.__name__, name), naming)
    )
    return (own, *tuples)


def _union_decls(cls: type, naming: Naming) -> tuple[UnionType, ...]:
    return tuple(
        UnionType(
            name,
            table_of(name),
            tuple(table_of(_type_name(m)) for m in _members(h, naming)),
        )
        for field, hint in _hints(cls, naming).items()
        for h in _contained(hint, naming)
        if _is_union(h) and len(_members(h, naming)) > 1 and _all_nodes(h, naming)
        for name in (_union_name(h, naming, _Owner(cls.__name__, field)),)
    )


def _type_name(hint: Hint) -> str:
    if isinstance(hint, type):
        return hint.__name__
    raise TypeError(f"{hint!r} is not a class")


def _all_nodes(hint: Hint, naming: Naming) -> bool:
    return all(_is_node(m) for m in _members(hint, naming))


def schema_of(roots: tuple[type, ...], naming: Naming) -> Schema:
    classes = tuple(c for c in reachable(roots, naming) if c is not naming.location)
    unions = reduce(
        lambda found, u: found if any(f.name == u.name for f in found) else (*found, u),
        (u for c in classes for u in _union_decls(c, naming)),
        (),
    )
    return Schema(
        tuple(n for c in classes for n in _node_types(c, naming)),
        tuple(sorted(unions, key=lambda u: u.table)),
    )
