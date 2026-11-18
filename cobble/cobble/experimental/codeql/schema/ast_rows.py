"""A parsed value's rows in the generated tables, walked by the schema its types produced."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import Field, dataclass
from enum import Enum
from functools import singledispatchmethod
from typing import ClassVar, Protocol

from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.schema.dbscheme import LOCATIONS, child_table, present
from cobble.experimental.codeql.schema.schema import NodeField, NodeType, Schema
from cobble.experimental.codeql.schema.shape import (
    Absent,
    Keyed,
    Located,
    NodeRef,
    Repeated,
    Scalar,
    Shape,
)
from cobble.experimental.codeql.trap_row import Column, TrapRow, define
from cobol_asg.source_span import SourceSpan

Rows = tuple[TrapRow, ...]


class Node(Protocol):
    """A dataclass instance: what a node type's rows are read from."""

    __dataclass_fields__: ClassVar[dict[str, Field[Value]]]


Value = (
    str
    | int
    | Enum
    | SourceSpan
    | Node
    | tuple["Value", ...]
    | Sequence["Value"]
    | Mapping[str, "Value"]
    | None
)


@dataclass(frozen=True)
class _Written:
    """A field's columns on its owner's row, and the rows it adds."""

    columns: tuple[Column, ...]
    rows: Rows


_NOTHING = _Written((), ())


Facts = Callable[[Value, Label], Rows]


def no_facts(value: Value, label: Label) -> Rows:
    return ()


@dataclass(frozen=True)
class AstWriter:
    """A node's label is its parent's label and the field's position, so labels
    are stable without a counter. ``facts`` adds the rows a language derives for
    a node beyond its fields -- which storage a name denotes, say."""

    schema: Schema
    file: Label
    facts: Facts = no_facts

    def rows(self, value: Value, table: str, label: Label) -> Rows:
        node = self._node(value, table)
        written = tuple(
            self._field(node, f, _read(value, f), label, Label(f"{label.name}_{i}"))
            for i, f in enumerate(node.fields)
        )
        columns = tuple(c for w in written for c in w.columns)
        rows = tuple(r for w in written for r in w.rows)
        own = TrapRow(f"{node.table}_def", (label, *columns))
        return (define(label), *rows, own, *self.facts(value, label))

    def _node(self, value: Value, table: str) -> NodeType:
        if isinstance(value, tuple):
            return next(n for n in self.schema.nodes if n.table == table)
        return self.schema.node_of(type(value))

    def _field(
        self, node: NodeType, field: NodeField, value: Value, owner: Label, label: Label
    ) -> _Written:
        return self._written(field.shape, child_table(node, field), value, owner, label)

    @singledispatchmethod
    def _written(
        self, shape: Shape, table: str, value: Value, owner: Label, label: Label
    ) -> _Written:
        """A column on the owner's row, and the rows of the node it names."""
        column, rows = self._value(shape, value, label)
        return _Written((column,), rows)

    @_written.register
    def _(
        self, shape: Absent, table: str, value: Value, owner: Label, label: Label
    ) -> _Written:
        return self._absent(table, shape.inner, value, owner, label)

    @_written.register
    def _(
        self, shape: Repeated, table: str, value: Value, owner: Label, label: Label
    ) -> _Written:
        return self._repeated(table, shape.element, value, owner, label)

    @_written.register
    def _(
        self, shape: Keyed, table: str, value: Value, owner: Label, label: Label
    ) -> _Written:
        return self._keyed(table, shape.value, value, owner, label)

    @singledispatchmethod
    def _value(self, shape: Shape, value: Value, label: Label) -> tuple[Column, Rows]:
        raise TypeError(f"{shape} is not one value")

    @_value.register
    def _(self, shape: Scalar, value: Value, label: Label) -> tuple[Column, Rows]:
        return _scalar(value), ()

    @_value.register
    def _(self, shape: NodeRef, value: Value, label: Label) -> tuple[Column, Rows]:
        return label, self.rows(value, shape.name, label)

    @_value.register
    def _(self, shape: Located, value: Value, label: Label) -> tuple[Column, Rows]:
        return _location(self.file, label, value)

    def _absent(
        self, table: str, inner: Shape, value: Value, owner: Label, label: Label
    ) -> _Written:
        match value:
            case None:
                return _NOTHING
            case _:
                column, rows = self._value(inner, value, label)
                return _Written((), (*rows, TrapRow(table, (owner, column))))

    def _repeated(
        self, table: str, element: Shape, value: Value, owner: Label, label: Label
    ) -> _Written:
        return self._positioned(
            table, element, tuple(enumerate(_items(value))), owner, label
        )

    def _positioned(
        self,
        table: str,
        element: Shape,
        items: tuple[tuple[int, Value], ...],
        owner: Label,
        label: Label,
    ) -> _Written:
        written = tuple(
            (j, self._value(element, item, Label(f"{label.name}_{j}")))
            for j, item in items
        )
        return _Written(
            (),
            tuple(
                row
                for j, (column, rows) in written
                for row in (*rows, TrapRow(table, (owner, j, column)))
            ),
        )

    def _keyed(
        self, table: str, entry: Shape, value: Value, owner: Label, label: Label
    ) -> _Written:
        entries = tuple(enumerate(_entries(value).items()))
        keys = tuple(TrapRow(table, (owner, j, key)) for j, (key, _) in entries)
        held = tuple((j, item) for j, (_, item) in entries if _holds(item))
        values = self._positioned(f"{table}_value", present(entry), held, owner, label)
        return _Written((), (*keys, *values.rows))


def _holds(value: Value) -> bool:
    """A map's ``None`` is a key with no value, written as no value row."""
    match value:
        case None:
            return False
        case _:
            return True


def _read(value: Value, field: NodeField) -> Value:
    match value, field.access:
        case tuple(), int(position):
            return value[position]
        case _, str(name):
            return getattr(value, name)
        case _:
            raise TypeError(f"{field.name} cannot be read from {type(value).__name__}")


def _scalar(value: Value) -> Column:
    match value:
        case Enum():
            return str(value.value)
        case str() | int():
            return value
        case _:
            raise TypeError(f"{type(value).__name__} is not a scalar")


def _items(value: Value) -> Sequence[Value]:
    match value:
        case str() | Mapping():
            raise TypeError(f"{type(value).__name__} is not a sequence")
        case Sequence():
            return value
        case _:
            raise TypeError(f"{type(value).__name__} is not a sequence")


def _entries(value: Value) -> Mapping[str, Value]:
    match value:
        case Mapping():
            return value
        case _:
            raise TypeError(f"{type(value).__name__} is not a map")


def _location(file: Label, label: Label, span: Value) -> tuple[Column, Rows]:
    match span:
        case SourceSpan():
            location = Label(f"l{label.name}")
            row = TrapRow(
                LOCATIONS,
                (
                    location,
                    file,
                    span.line_start,
                    span.col_start,
                    span.line_end,
                    span.col_end,
                ),
            )
            return location, (define(location), row)
        case _:
            raise TypeError(f"{type(span).__name__} is not a source span")
