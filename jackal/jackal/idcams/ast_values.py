"""Shared AST value types and shapes for the comprehensive IDCAMS grammar.

Distinct from jackal.value_parts.Value (JCL's Literal/Symbol substitution
model) -- IDCAMS is a separate small language with its own value grammar
(plain names, quoted strings, hex/binary literals, integers), not JCL
symbol substitution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Union

_QUALIFIER = r"[A-Z#@$][A-Z0-9#@$]*"
_PLAIN_NAME = re.compile(rf"^{_QUALIFIER}(\.{_QUALIFIER})*$")
_GENERIC_NAME = re.compile(rf"^{_QUALIFIER}(\.{_QUALIFIER})*\.\*(\.{_QUALIFIER})?$")


@dataclass(frozen=True)
class Name:
    text: str
    generic: bool = False

    @staticmethod
    def parse(text: str) -> "Name":
        if _PLAIN_NAME.match(text):
            return Name(text=text, generic=False)
        if _GENERIC_NAME.match(text):
            return Name(text=text, generic=True)
        raise ValueError(f"Invalid entry/generic name: {text!r}")


@dataclass(frozen=True)
class QuotedString:
    text: str  # de-escaped ('' -> ')


@dataclass(frozen=True)
class HexLiteral:
    raw: str


@dataclass(frozen=True)
class BinLiteral:
    raw: str


Value = Union[Name, QuotedString, HexLiteral, BinLiteral, int]


@dataclass(frozen=True)
class SpaceAllocation:
    unit: Literal["CYLINDERS", "KILOBYTES", "MEGABYTES", "RECORDS", "TRACKS"]
    primary: int
    secondary: int | None = None


@dataclass(frozen=True)
class Retention:
    to_date: str | None = None
    for_days: int | None = None
