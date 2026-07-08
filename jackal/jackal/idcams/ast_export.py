"""Typed AST for IDCAMS EXPORT (comprehensive grammar).

Field list transcribed verbatim from the design spec's `Export` section
(2026-07-08-idcams-comprehensive-grammar-design.md).

Per the plan's ratified structural single-occurrence pattern (see
ast_repro.py/ast_delete.py/ast_alter.py for prior art), EXPORT has three
genuine "pick one" choice groups, each flat-grammar + transformer-enforced
(ams.lark's EXPORT section, ComprehensiveIdcamsTransformer.export()):
  - OUTFILE/OUTDATASET (required, exactly one)
  - CIMODE/RECORDMODE (optional, at most one -- which processing mode)
  - TEMPORARY/PERMANENT (optional, at most one -- which export kind)

ERASE/NOERASE, INHIBITSOURCE/NOINHIBITSOURCE, INHIBITTARGET/
NOINHIBITTARGET, and PURGE/NOPURGE are ordinary simple ON/OFF toggle
pairs -- left as freely-repeatable parameters per the plan's ratified
scope for simple booleans, NOT given the flat-choice-group treatment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name

__all__ = ["Export"]


@dataclass(frozen=True)
class Export:
    entry: Name
    outfile: str | None = None  # mutually exclusive with outdataset
    outdataset: Name | None = None
    mode: Literal["CIMODE", "RECORDMODE"] | None = None
    erase: bool | None = None
    infile: str | None = None
    inhibit_source: bool | None = None
    inhibit_target: bool | None = None
    purge: bool | None = None
    temporary: bool | None = None  # TEMPORARY | PERMANENT
    rls_source: Literal["NO", "YES", "QUIESCE"] | None = None
