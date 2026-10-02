"""A reachability walk after one level: what to expand next, what it has written, and
the rows this level adds."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Edge
from cobble.dataflow.srccfg.reach.reach_state import ReachState
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow


@dataclass(frozen=True)
class ReachProgress:
    frontier: tuple[ReachState, ...]
    seen: frozenset[ReachState]
    nodes: frozenset[str]
    edges: frozenset[Edge]
    events: frozenset[CfgRow]
    written: tuple[CfgRow, ...] = ()
    finished: bool = False
