"""A graph-file node row whose node is defined in a file."""

from pathlib import Path
from typing import Literal

from cobble.knowledge_graph.graph_types import AttrValue, GraphNode, NodeKind
from cobble.knowledge_graph.row_type import RowType
from pydantic import BaseModel, ConfigDict


class PathNodeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[RowType.NODE]
    id: str
    kind: NodeKind
    file_path: str
    file_path_reason: None
    attrs: dict[str, AttrValue]

    def to_node(self) -> GraphNode:
        return GraphNode(
            id=self.id,
            kind=self.kind,
            location=Path(self.file_path),
            attrs=dict(self.attrs),
        )
