"""A JCL value (a DSN name, a PARM) as literal text and &SYMBOL references, classified by the bridge's lexer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class SymbolName:
    text: str


@dataclass(frozen=True)
class Literal:
    text: str

    def resolved_text(self, value: Value) -> str:
        return self.text


@dataclass(frozen=True)
class Symbol:
    name: SymbolName

    def resolved_text(self, value: Value) -> str:
        raise ValueError(f"Unresolved symbol '&{self.name.text}' in value {value!r}")


ValuePart: TypeAlias = Literal | Symbol
Value: TypeAlias = tuple[ValuePart, ...]


def literal(text: str) -> Value:
    return (Literal(text),)


def resolve(value: Value) -> str:
    return "".join(part.resolved_text(value) for part in value)
