"""Literal/Symbol value parts: the typed replacement for a plain str wherever
a JCL value (a DSN name, a PARM) can contain either literal text or a
&SYMBOL reference. A part's classification always comes from the jcl-bridge
lexer's own SYMBOLIC token type (see JclSerializer.java's buildValueParts) —
never re-inferred here from string content.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Literal:
    text: str


@dataclass(frozen=True)
class Symbol:
    name: str  # symbol name, no leading '&'


type ValuePart = Literal | Symbol
type Value = tuple[ValuePart, ...]


def literal(text: str) -> Value:
    """Build a Value out of a single, already-known-literal string."""
    return (Literal(text),)


def resolve(value: Value) -> str:
    """Concatenate value to a plain string.

    Raises ValueError naming the symbol if any part is an unresolved Symbol
    — a genuine correctness improvement over silently carrying "&SYMBOL" as
    if it were literal dataset-name text.
    """
    parts: list[str] = []
    for part in value:
        match part:
            case Literal(text=t):
                parts.append(t)
            case Symbol(name=n):
                raise ValueError(f"Unresolved symbol '&{n}' in value {value!r}")
    return "".join(parts)
