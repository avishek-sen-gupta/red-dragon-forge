"""GraphWriter — streaming sink for the knowledge graph.

Edges stream to edges.jsonl deduped keep-first (reproducing _dedupe_edges).
Nodes are buffered in a dict and merged (file_path = existing or new; attrs
union) — reproducing merge_graph, including the bare-endpoint-then-real upgrade —
then flushed to nodes.jsonl on close(). Files are written to temp paths and
renamed on close() so a crash leaves no truncated output. Structurally satisfies
cicada's GraphSink.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cobble.interpreter.project.graph_types import GraphEdge, GraphNode, NodeKind


class GraphWriter:
    def __init__(self, nodes_path: Path, edges_path: Path) -> None:
        self._nodes_path = nodes_path
        self._edges_path = edges_path
        self._nodes: dict[tuple[NodeKind, str], dict[str, Any]] = {}
        self._edge_seen: set[tuple] = set()
        self._etmp = edges_path.with_suffix(edges_path.suffix + ".tmp")
        self._ef = self._etmp.open("w")

    def add_node(self, node: GraphNode) -> None:
        key = (node.kind, node.id)
        cur = self._nodes.get(key)
        if cur is None:
            self._nodes[key] = {"file_path": node.file_path, "attrs": dict(node.attrs)}
        else:
            cur["file_path"] = cur["file_path"] or node.file_path
            cur["attrs"] = {**cur["attrs"], **node.attrs}

    def add_edge(self, edge: GraphEdge) -> None:
        # Defensively buffer bare endpoint nodes, reproducing merge_graph's
        # endpoint synthesis exactly: an edge whose endpoints were never
        # explicitly add_node'd still yields those nodes. add_node buffer-merges,
        # so a later real node (file_path/attrs) upgrades the bare one, and an
        # explicitly-added endpoint is harmlessly deduped.
        self.add_node(GraphNode(id=edge.source, kind=edge.source_kind))
        self.add_node(GraphNode(id=edge.target, kind=edge.target_kind))
        key = (edge.source, edge.source_kind, edge.target, edge.target_kind, edge.kind)
        if key in self._edge_seen:
            return
        self._edge_seen.add(key)
        self._ef.write(
            json.dumps(
                {
                    "source": edge.source,
                    "source_kind": edge.source_kind.value,
                    "target": edge.target,
                    "target_kind": edge.target_kind.value,
                    "kind": edge.kind.value,
                    "attrs": edge.attrs,
                }
            )
            + "\n"
        )

    def add_all(self, nodes, edges) -> None:
        for n in nodes:
            self.add_node(n)
        for e in edges:
            self.add_edge(e)

    def close(self) -> None:
        self._ef.close()
        ntmp = self._nodes_path.with_suffix(self._nodes_path.suffix + ".tmp")
        with ntmp.open("w") as nf:
            for (kind, node_id), data in self._nodes.items():
                nf.write(
                    json.dumps(
                        {
                            "id": node_id,
                            "kind": kind.value,
                            "file_path": data["file_path"],
                            "attrs": data["attrs"],
                        }
                    )
                    + "\n"
                )
        ntmp.rename(self._nodes_path)
        self._etmp.rename(self._edges_path)

    def __enter__(self) -> "GraphWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
