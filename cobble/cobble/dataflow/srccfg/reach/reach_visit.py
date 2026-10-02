"""What expanding one state gives: the steps out of it, and the facts it records."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.reach.reach_step import ReachStep
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow


@dataclass(frozen=True)
class ReachVisit:
    steps: tuple[ReachStep, ...]
    events: tuple[CfgRow, ...]
