"""A generation data group's base: its limit, its roll-off rules and its active generations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Empty(Enum):
    EMPTY = "EMPTY"
    NOEMPTY = "NOEMPTY"


class Scratch(Enum):
    SCRATCH = "SCRATCH"
    NOSCRATCH = "NOSCRATCH"


@dataclass(frozen=True)
class GdgBase:
    name: str
    limit: int
    empty: Empty
    scratch: Scratch
    generations: tuple[int, ...]
