"""Typed AST for IDCAMS PRINT (comprehensive grammar).

Field list transcribed verbatim from the design spec's `Print` section
(2026-07-08-idcams-comprehensive-grammar-design.md). PRINT has the identical
four-kind RangeStart/RangeEnd shape as REPRO (Task 7) -- reused verbatim,
not redefined, per the design spec's note under the Print section and the
plan's interface contract for this task.

`format` (the CHARACTER/DUMP/HEX optional 3-way choice) is left `None` when
not specified, rather than defaulting to "DUMP" in this layer: this module
is parsing-only, not execution, so applying the manual's documented default
belongs to a future execution layer, not the AST/grammar. `detail` on
`Listcat` (ast_listcat.py) makes the same "leave None, don't default here"
call for consistency, even though the design spec's dataclass default
differs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_repro import RangeEnd, RangeStart
from jackal.idcams.ast_values import Name

__all__ = ["Print"]


@dataclass(frozen=True)
class Print:
    infile: str | None = None  # mutually exclusive with indataset
    indataset: Name | None = None
    format: Literal["CHARACTER", "DUMP", "HEX"] | None = None  # manual default: DUMP
    cimode: bool | None = None
    dbcs: bool = False
    range_start: RangeStart | None = None
    range_end: RangeEnd | None = None
    insert_shift: tuple[tuple[int, int], ...] = ()
    insert_all: bool = False
    skip_dbcs_check: tuple[tuple[int, int], ...] = ()
    no_dbcs_check: bool = False
    outfile: str | None = None
    rls_source: Literal["NO", "YES", "QUIESCE"] | None = None
