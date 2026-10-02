"""One reachability state: a node, and the PERFORMs open there, innermost last."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.reach.reach_frame import ReachFrame


@dataclass(frozen=True)
class ReachState:
    node: str
    stack: tuple[ReachFrame, ...]
