"""Immutable JCL job model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jackal.dsn import DSN


class DispStatus(Enum):
    NEW = "NEW"
    OLD = "OLD"
    SHR = "SHR"
    MOD = "MOD"


class DispNormal(Enum):
    PASS = "PASS"
    CATLG = "CATLG"
    KEEP = "KEEP"
    DELETE = "DELETE"


class DatasetOrg(Enum):
    PS = "PS"
    KSDS = "KSDS"


class CondOp(Enum):
    GT = "GT"
    GE = "GE"
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"


@dataclass(frozen=True)
class Cond:
    code: int
    op: CondOp
    step: str = ""  # "" = test all prior executed steps


@dataclass(frozen=True)
class Disp:
    status: DispStatus
    normal: DispNormal
    abnormal: DispNormal


@dataclass(frozen=True)
class DD:
    ddname: str
    dsn: DSN
    disp: Disp
    in_stream: tuple[str, ...] = ()
    sysout: bool = False


@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]
    conds: tuple[Cond, ...] = ()
    parm: str = ""


@dataclass(frozen=True)
class Job:
    name: str
    steps: tuple[Step, ...]
    cond: tuple[Cond, ...] = ()
