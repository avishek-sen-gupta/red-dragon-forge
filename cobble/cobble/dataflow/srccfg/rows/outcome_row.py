"""A reach row: one way a branch of the walk ended, and the node it ended at."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobble.dataflow.srccfg.rows.reach_outcome import ReachOutcome
from pydantic import BaseModel, ConfigDict


class CfgOutcomeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.OUTCOME]
    kind: ReachOutcome
    node: str
