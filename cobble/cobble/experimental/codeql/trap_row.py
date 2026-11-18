"""One TRAP line: a label's definition, or a tuple of a dbscheme table."""

from dataclasses import dataclass
from functools import singledispatch

from cobble.experimental.codeql.label import Label

Column = Label | str | int


def _column(value: Column) -> str:
    if isinstance(value, Label):
        return value.text()
    return _literal(value)


@singledispatch
def _literal(value: int) -> str:
    return str(value)


@_literal.register
def _(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


@_literal.register
def _(value: bool) -> str:
    return "true" if value else "false"


@dataclass(frozen=True)
class TrapRow:
    """``table`` empty means the row defines ``columns[0]`` as a fresh label."""

    table: str
    columns: tuple[Column, ...]

    def text(self) -> str:
        if not self.table:
            return f"{_column(self.columns[0])}=*"
        return f"{self.table}({', '.join(_column(c) for c in self.columns)})"


def define(label: Label) -> TrapRow:
    return TrapRow("", (label,))


def trap_text(rows: tuple[TrapRow, ...]) -> str:
    return "".join(row.text() + "\n" for row in rows)
