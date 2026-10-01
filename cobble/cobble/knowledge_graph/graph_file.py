"""The graph file: one JSON line per node and per edge, each tagged with which it is."""

from pathlib import Path

from cobble.file_location import NoFileLocation
from cobble.knowledge_graph.edge_row import EdgeRow
from cobble.knowledge_graph.graph_types import GraphEdge, GraphNode
from cobble.knowledge_graph.path_node_row import PathNodeRow
from cobble.knowledge_graph.reason_node_row import ReasonNodeRow
from cobble.knowledge_graph.row_type import RowType
from pydantic import TypeAdapter

GraphRow = PathNodeRow | ReasonNodeRow | EdgeRow

_ROWS: TypeAdapter[GraphRow] = TypeAdapter(GraphRow)


def _rows(path: Path) -> tuple[GraphRow, ...]:
    return tuple(
        _ROWS.validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def read_graph(path: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    rows = _rows(path)
    return (
        [row.to_node() for row in rows if not isinstance(row, EdgeRow)],
        [row.to_edge() for row in rows if isinstance(row, EdgeRow)],
    )


def node_row(node: GraphNode) -> PathNodeRow | ReasonNodeRow:
    match node.location:
        case Path() as path:
            return PathNodeRow(
                type=RowType.NODE,
                id=node.id,
                kind=node.kind,
                file_path=str(path),
                file_path_reason=None,
                attrs=node.attrs,
            )
        case NoFileLocation(reason=reason):
            return ReasonNodeRow(
                type=RowType.NODE,
                id=node.id,
                kind=node.kind,
                file_path=None,
                file_path_reason=reason,
                attrs=node.attrs,
            )


def edge_row(edge: GraphEdge) -> EdgeRow:
    return EdgeRow(
        type=RowType.EDGE,
        source=edge.source,
        source_kind=edge.source_kind,
        target=edge.target,
        target_kind=edge.target_kind,
        kind=edge.kind,
        attrs=edge.attrs,
    )
