"""A reach row, always last: the seed, and how many states the walk visited."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgSummaryRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.SUMMARY]
    seed: str
    states: int
