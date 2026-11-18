"""A TRAP label: one entity of the database, named by where it sits in the program."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Label:
    name: str

    def text(self) -> str:
        return f"#{self.name}"
