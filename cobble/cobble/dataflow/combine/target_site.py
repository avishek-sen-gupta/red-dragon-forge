"""TargetSite — a dynamic call site as the fixpoint's targets table names it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetSite:
    transfer: str
    expression: str
