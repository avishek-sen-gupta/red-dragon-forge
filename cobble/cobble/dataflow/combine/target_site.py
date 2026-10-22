"""TargetSite — a dynamic site as the fixpoint's targets table names it."""

from dataclasses import dataclass, field

from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.jumps.fact import Fact


@dataclass(frozen=True)
class TargetSite:
    """``operand`` is a file site's operand fact; a call site's travels in its jump."""

    transfer: str
    expression: str
    kind: TargetKind = TargetKind.PROGRAM
    operand: Fact = field(default_factory=Fact)
