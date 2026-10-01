"""A graph-file node row whose node has no file, and says why."""

from typing import Literal

from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.knowledge_graph.graph_types import AttrValue, GraphNode, NodeKind
from cobble.knowledge_graph.row_type import RowType
from pydantic import BaseModel, ConfigDict


class ReasonNodeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[RowType.NODE]
    id: str
    kind: NodeKind
    file_path: None
    file_path_reason: FileLocationReason
    attrs: dict[str, AttrValue]

    def to_node(self) -> GraphNode:
        return GraphNode(
            id=self.id,
            kind=self.kind,
            location=NoFileLocation(self.file_path_reason),
            attrs=dict(self.attrs),
        )
