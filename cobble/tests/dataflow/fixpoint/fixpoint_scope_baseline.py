"""One fixture program's recorded fixpoint cost in each scope."""

from __future__ import annotations

from dataclasses import dataclass

from tests.dataflow.fixpoint.fixpoint_cost import FixpointCost


@dataclass(frozen=True)
class FixpointScopeBaseline:
    """The whole-program cost and the call-target cost, on the same commit."""

    program: str
    whole: FixpointCost
    call_targets: FixpointCost
