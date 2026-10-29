"""One named, typed column of a relation."""

from dataclasses import dataclass

from cobble.experimental.datalog.column_type import ColumnType


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType

    def declared(self) -> str:
        return f"{self.name}:{self.type}"


def symbol(name: str) -> Column:
    return Column(name, ColumnType.SYMBOL)


def number(name: str) -> Column:
    return Column(name, ColumnType.NUMBER)
