"""One TRAP line: a label's definition, or a tuple of a dbscheme table."""

from dataclasses import dataclass

from cobble.experimental.codeql.label import Label

Column = Label | str | int


def _column(value: Column) -> str:
    if isinstance(value, Label):
        return value.text()
    return _literal(value)


def _literal(value: str | int) -> str:
    return (
        '"' + value.replace('"', '""') + '"' if isinstance(value, str) else str(value)
    )


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
