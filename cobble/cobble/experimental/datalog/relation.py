"""A relation's name and columns: the one definition its facts file and schema line share."""

from dataclasses import dataclass

from cobble.experimental.datalog.column import Column


@dataclass(frozen=True)
class Relation:
    name: str
    columns: tuple[Column, ...]

    def schema(self) -> str:
        columns = ", ".join(column.declared() for column in self.columns)
        return f".decl {self.name}({columns})\n.input {self.name}\n"
