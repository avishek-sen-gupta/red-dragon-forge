"""Immutable JCL job model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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


@dataclass(frozen=True)
class Disp:
    status: DispStatus
    normal: DispNormal
    abnormal: DispNormal


@dataclass(frozen=True)
class DD:
    ddname: str
    dsn: str
    disp: Disp


@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]


@dataclass(frozen=True)
class Job:
    name: str
    steps: tuple[Step, ...]
