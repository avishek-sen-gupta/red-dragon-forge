"""Typed AST for IDCAMS VERIFY (comprehensive grammar).

Field list transcribed verbatim from the design spec's `Verify` section
(2026-07-08-idcams-comprehensive-grammar-design.md). This is the lightest
command in the comprehensive-grammar plan.

Per the plan's ratified structural single-occurrence pattern (see
ast_export.py/ast_import.py/ast_repro.py for prior art), VERIFY has one
genuine required "pick one" choice group, flat-grammar + transformer-
enforced (ams.lark's VERIFY section, ComprehensiveIdcamsTransformer.verify()):
  - FILE/DATASET (required, exactly one)

RECOVER is an ordinary bare flag -- no mutual-exclusivity machinery needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from jackal.idcams.ast_values import Name

__all__ = ["Verify"]


@dataclass(frozen=True)
class Verify:
    file: str | None = None  # mutually exclusive with dataset
    dataset: Name | None = None
    recover: bool = False
