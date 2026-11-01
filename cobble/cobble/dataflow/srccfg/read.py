"""One name a CFG node reads, and how it reads it."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from cobble.dataflow.srccfg.read_kind import ReadKind


@dataclass(frozen=True)
class Read:
    name: str
    kind: ReadKind


def reads_of(names: Iterable[str], kind: ReadKind) -> tuple[Read, ...]:
    return tuple(Read(name, kind) for name in names)


def names_of(reads: Iterable[Read]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(read.name for read in reads))


def copied_names(reads: Iterable[Read]) -> tuple[str, ...]:
    return names_of(read for read in reads if read.kind is ReadKind.COPIED)
