"""The graph file: one node or edge per line, nodes first."""

from __future__ import annotations

from pathlib import Path

from cobble.experimental.partition.edge_line import EdgeLine
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.node_line import NodeLine
from pydantic import TypeAdapter

_LINE: TypeAdapter[NodeLine | EdgeLine] = TypeAdapter(NodeLine | EdgeLine)


def write_graph(path: Path, graph: FieldGraph) -> None:
    with path.open("w", encoding="utf-8") as out:
        out.writelines(
            f"{NodeLine(node=node).model_dump_json()}\n" for node in graph.nodes
        )
        out.writelines(
            f"{EdgeLine(edge=edge).model_dump_json()}\n" for edge in graph.edges
        )


def read_graph(path: Path) -> FieldGraph:
    with path.open(encoding="utf-8") as lines:
        parsed = tuple(_LINE.validate_json(line) for line in lines if line.strip())
    return FieldGraph(
        nodes=tuple(line.node for line in parsed if isinstance(line, NodeLine)),
        edges=tuple(line.edge for line in parsed if isinstance(line, EdgeLine)),
    )
