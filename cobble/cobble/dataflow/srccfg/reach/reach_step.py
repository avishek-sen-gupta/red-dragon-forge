"""One edge a reachability walk takes, and the state it arrives in."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Edge
from cobble.dataflow.srccfg.reach.reach_state import ReachState


@dataclass(frozen=True)
class ReachStep:
    edge: Edge
    state: ReachState
