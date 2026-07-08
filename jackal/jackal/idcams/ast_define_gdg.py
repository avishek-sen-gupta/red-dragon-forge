"""Typed AST for IDCAMS DEFINE GENERATIONDATAGROUP (comprehensive grammar).

DEFINE GENERATIONDATAGROUP (GDG) creates a generation data group base
catalog entry. Unlike DEFINE CLUSTER/ALTERNATEINDEX it has no DATA(...)/
INDEX(...) trailer clauses and no mutually-exclusive-choice groups (no
space allocation, no ALTKEYS-style pair) -- every parameter is freely
repeatable, so the grammar rule needs none of Task 2/3's DFA-state-machine
machinery.

Field list transcribed verbatim from the design spec's
`DefineGenerationDataGroup` section
(2026-07-08-idcams-comprehensive-grammar-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name

__all__ = ["DefineGenerationDataGroup"]


@dataclass(frozen=True)
class DefineGenerationDataGroup:
    name: Name
    limit: int
    catalog: str | None = None
    empty: bool | None = None  # EMPTY | NOEMPTY
    extended: bool | None = None  # EXTENDED | NOEXTENDED
    order: Literal["FIFO", "LIFO"] | None = None
    owner: str | None = None
    purge: bool | None = None  # PURGE | NOPURGE
    scratch: bool | None = None  # SCRATCH | NOSCRATCH
