"""Frozen dataclass command objects produced by the IDCAMS parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

Command = Union["Delete", "DefineCluster", "Repro", "IfMaxcc"]


@dataclass(frozen=True)
class Delete:
    dsn: str


@dataclass(frozen=True)
class DefineCluster:
    name: str
    key_length: int
    key_offset: int
    record_size: int


@dataclass(frozen=True)
class Repro:
    infile_dd: str
    outfile_dd: str


@dataclass(frozen=True)
class IfMaxcc:
    op: str
    value: int
    set_value: int
