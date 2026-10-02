"""A reach row: a PERFORM whose range the program does not declare."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgUnresolvedRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.UNRESOLVED]
    node: str
