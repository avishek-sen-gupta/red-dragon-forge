"""The graph file: one node or edge per line, nodes first, read a line at a time with progress every tenth of the file."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from cobble.experimental.partition.edge_line import EdgeLine
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_line import NodeLine
from cobble.experimental.partition.progress import counted
from cobble.experimental.partition.tally import GRAPH, tenths
from pydantic import TypeAdapter

_LINE: TypeAdapter[NodeLine | EdgeLine] = TypeAdapter(NodeLine | EdgeLine)


def write_graph(path: Path, graph: FieldGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        out.writelines(
            f"{NodeLine(node=node).model_dump_json()}\n" for node in graph.nodes
        )
        out.writelines(
            f"{EdgeLine(edge=edge).model_dump_json()}\n" for edge in graph.edges
        )


def _texts(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8") as lines:
        yield from (line for line in lines if line.strip())


def _shared_node(node: GraphNode) -> GraphNode:
    return replace(
        node,
        id=sys.intern(node.id),
        program=sys.intern(node.program),
        record=sys.intern(node.record),
    )


def _shared_edge(edge: GraphEdge) -> GraphEdge:
    return replace(
        edge,
        source=sys.intern(edge.source),
        target=sys.intern(edge.target),
        barrier=sys.intern(edge.barrier),
        reasons=tuple(sys.intern(reason) for reason in edge.reasons),
    )


def _read(text: str) -> GraphNode | GraphEdge:
    line = _LINE.validate_json(text)
    if isinstance(line, NodeLine):
        return _shared_node(line.node)
    return _shared_edge(line.edge)


def read_graph(path: Path) -> FieldGraph:
    total = sum(1 for _ in _texts(path))
    step = tenths(GRAPH, "lines read", total)
    read = tuple(_read(text) for text in counted(_texts(path), step, total))
    return FieldGraph(
        nodes=tuple(item for item in read if isinstance(item, GraphNode)),
        edges=tuple(item for item in read if isinstance(item, GraphEdge)),
    )
