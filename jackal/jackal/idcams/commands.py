"""Frozen dataclass command objects produced by the IDCAMS parser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from catnip.gdg import Empty, GdgBase, GdgOrder, Scratch

_LIMIT = 255
_EXTENDED_LIMIT = 999


@dataclass(frozen=True)
class Delete:
    entries: tuple[str, ...]
    purge: bool


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
    order: GdgOrder
    extended: bool

    def within_limit(self) -> bool:
        return 1 <= self.limit <= (_EXTENDED_LIMIT if self.extended else _LIMIT)

    def base(self) -> GdgBase:
        return GdgBase(self.name, self.limit, self.empty, self.scratch, self.order, ())


@dataclass(frozen=True)
class Repro:
    infile_dd: str
    outfile_dd: str


class Cc(Enum):
    MAXCC = "MAXCC"
    LASTCC = "LASTCC"


class CcOp(Enum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    LT = "LT"
    GE = "GE"
    LE = "LE"


@dataclass(frozen=True)
class Condition:
    field: Cc
    op: CcOp
    value: int


@dataclass(frozen=True)
class SetCc:
    field: Cc
    value: int


@dataclass(frozen=True)
class Cancel:
    pass


@dataclass(frozen=True)
class VerifyFile:
    ddname: str


@dataclass(frozen=True)
class VerifyDataset:
    name: str


@dataclass(frozen=True)
class Verify:
    target: VerifyFile | VerifyDataset


@dataclass(frozen=True)
class If:
    condition: Condition
    then: tuple[Command, ...]
    otherwise: tuple[Command, ...]


class Verb(Enum):
    ALTER = "ALTER"
    BLDINDEX = "BLDINDEX"
    DEFINE_ALTERNATEINDEX = "DEFINE ALTERNATEINDEX"
    DEFINE_CLUSTER = "DEFINE CLUSTER"
    DEFINE_GDG = "DEFINE GENERATIONDATAGROUP"
    DEFINE_NONVSAM = "DEFINE NONVSAM"
    DEFINE_PATH = "DEFINE PATH"
    DELETE = "DELETE"
    EXPORT = "EXPORT"
    IMPORT = "IMPORT"
    LISTCAT = "LISTCAT"
    PRINT = "PRINT"
    REPRO = "REPRO"
    VERIFY = "VERIFY"


@dataclass(frozen=True)
class NotExecuted:
    """A command jackal parsed but does not run: its verb, or a parameter it codes, is not modelled."""

    verb: Verb


Command: TypeAlias = (
    Delete
    | DefineCluster
    | DefineGdg
    | Repro
    | Verify
    | If
    | SetCc
    | Cancel
    | NotExecuted
)
