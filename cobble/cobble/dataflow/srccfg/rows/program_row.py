"""A src-cfg row opening one program's CFG."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgProgramRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.PROGRAM]
    program: str
    external: bool = False
