"""NDJSON export/import for the merged knowledge graph — one line per node,
one line per edge, following the same analysis-only NDJSON precedent
interpreter.project.cobol_connections already established.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def write_ndjson(graph: nx.MultiDiGraph, nodes_path: Path, edges_path: Path) -> None:
    """Write graph's nodes and edges as two NDJSON files."""
    with nodes_path.open("w") as f:
        for _key, data in graph.nodes(data=True):
            f.write(
                json.dumps(
                    {
                        "id": data["id"],
                        "kind": data["kind"].value,
                        "file_path": data["file_path"],
                        "attrs": data["attrs"],
                    }
                )
                + "\n"
            )

    with edges_path.open("w") as f:
        for source, target, data in graph.edges(data=True):
            f.write(
                json.dumps(
                    {
                        "source": source[1],
                        "source_kind": source[0].value,
                        "target": target[1],
                        "target_kind": target[0].value,
                        "kind": data["kind"].value,
                        "attrs": data["attrs"],
                    }
                )
                + "\n"
            )


def read_ndjson(
    nodes_path: Path, edges_path: Path
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Read (nodes, edges) back from NDJSON files written by write_ndjson."""
    nodes: list[GraphNode] = []
    with nodes_path.open() as f:
        for line in f:
            row = json.loads(line)
            nodes.append(
                GraphNode(
                    id=row["id"],
                    kind=NodeKind(row["kind"]),
                    file_path=row["file_path"],
                    attrs=row["attrs"],
                )
            )

    edges: list[GraphEdge] = []
    with edges_path.open() as f:
        for line in f:
            row = json.loads(line)
            edges.append(
                GraphEdge(
                    source=row["source"],
                    source_kind=NodeKind(row["source_kind"]),
                    target=row["target"],
                    target_kind=NodeKind(row["target_kind"]),
                    kind=EdgeKind(row["kind"]),
                    attrs=row["attrs"],
                )
            )

    return nodes, edges
