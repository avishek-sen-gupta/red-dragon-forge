"""A graph-file edge row."""

from typing import Literal

from cobble.knowledge_graph.graph_types import AttrValue, EdgeKind, GraphEdge, NodeKind
from cobble.knowledge_graph.row_type import RowType
from pydantic import BaseModel, ConfigDict


class EdgeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[RowType.EDGE]
    source: str
    source_kind: NodeKind
    target: str
    target_kind: NodeKind
    kind: EdgeKind
    attrs: dict[str, AttrValue]

    def to_edge(self) -> GraphEdge:
        return GraphEdge(
            source=self.source,
            source_kind=self.source_kind,
            target=self.target,
            target_kind=self.target_kind,
            kind=self.kind,
            attrs=dict(self.attrs),
        )
