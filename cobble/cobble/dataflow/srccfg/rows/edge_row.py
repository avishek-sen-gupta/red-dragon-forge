"""A src-cfg row holding one CFG edge."""

from typing import Literal

from cobble.dataflow.srccfg.cfg import Edge, EdgeKind
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgEdgeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.EDGE]
    program: str
    source: str
    target: str
    kind: EdgeKind

    def to_edge(self) -> Edge:
        return Edge(source=self.source, target=self.target, kind=self.kind)
