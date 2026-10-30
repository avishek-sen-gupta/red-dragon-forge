"""One fixture program's recorded fixpoint costs around the partial-overwrite split."""

from __future__ import annotations

from dataclasses import dataclass

from tests.dataflow.fixpoint.fixpoint_cost import FixpointCost


@dataclass(frozen=True)
class FixpointBaseline:
    """Before the split, with it, cut at fixed atoms, reverted, coalesced, round-robin, and call-matched PERFORMs."""

    program: str
    pre_split: FixpointCost
    split: FixpointCost
    atoms: FixpointCost
    reverted: FixpointCost
    coalesced: FixpointCost
    round_robin: FixpointCost
    call_matched: FixpointCost
