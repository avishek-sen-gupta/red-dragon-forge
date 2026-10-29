"""One relation and the rows a run gives it."""

from dataclasses import dataclass

from cobble.experimental.datalog.relation import Relation

Value = str | int
Row = tuple[Value, ...]


@dataclass(frozen=True)
class Facts:
    relation: Relation
    rows: tuple[Row, ...]
