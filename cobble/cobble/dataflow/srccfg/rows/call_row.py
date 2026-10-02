"""A src-cfg row holding one call joining two programs' CFGs."""

from typing import Literal

from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgCallRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.CALL]
    caller: str
    node: str
    transfer: str
    program: str
    entry: str
    resolved: bool
    commarea: str
    expression: str
    reasons: tuple[str, ...]
    certain: bool

    def to_call(self) -> BundleCall:
        return BundleCall(
            caller=self.caller,
            node=self.node,
            transfer=self.transfer,
            program=self.program,
            entry=self.entry,
            resolved=self.resolved,
            commarea=self.commarea,
            expression=self.expression,
            reasons=self.reasons,
            certain=self.certain,
        )
