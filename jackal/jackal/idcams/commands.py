"""Frozen dataclass command objects produced by the IDCAMS parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from jackal.gdg import Empty, GdgBase, Scratch

_LIMIT = 255
_EXTENDED_LIMIT = 999


@dataclass(frozen=True)
class Delete:
    dsn: str
    purge: bool = False


@dataclass(frozen=True)
class DefineCluster:
    name: str
    key_length: int
    key_offset: int
    record_size: int


@dataclass(frozen=True)
class DefineGdg:
    name: str
    limit: int
    empty: Empty
    scratch: Scratch
    extended: bool

    def within_limit(self) -> bool:
        return 1 <= self.limit <= (_EXTENDED_LIMIT if self.extended else _LIMIT)

    def base(self) -> GdgBase:
        return GdgBase(self.name, self.limit, self.empty, self.scratch, ())


@dataclass(frozen=True)
class Repro:
    infile_dd: str
    outfile_dd: str


@dataclass(frozen=True)
class IfMaxcc:
    op: str
    value: int
    set_value: int
    test_field: str = "MAXCC"


@dataclass(frozen=True)
class SetMaxcc:
    value: int


Command: TypeAlias = Delete | DefineCluster | DefineGdg | Repro | IfMaxcc | SetMaxcc
