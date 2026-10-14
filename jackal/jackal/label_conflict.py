"""One attribute on which an FD contradicts its dataset's label: the label's value and the FD's."""

from __future__ import annotations

from dataclasses import dataclass

from jackal.label_field import LabelField


@dataclass(frozen=True)
class LabelConflict:
    field: LabelField
    declared: str | int
    program: str | int

    def described(self, dsn: str) -> str:
        return f"{dsn}: {self.field.value}: declared {self.declared}, FD {self.program}"
