"""A reach row: a PERFORM of a range already open, stepped over rather than entered."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgRefusedRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.REFUSED]
    node: str
