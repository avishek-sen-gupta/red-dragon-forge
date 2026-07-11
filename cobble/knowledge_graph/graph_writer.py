"""GraphWriter — streaming sink for the knowledge graph.

Both nodes and edges stream to their .jsonl file deduped keep-first, on
first sighting, with no buffering. This is only correct because file_path is
resolved once, up front, by a CorpusIndex passed in at construction — every
occurrence of a given (kind, id), whether from an extractor's explicit
add_node or add_edge's own defensive endpoint-stub synthesis, resolves to
the same file_path no matter what order things arrive in. (Previously, node
identity was reconciled by buffering everything in a dict and merging
file_path = existing or new on every add_node, because file_path was only
opportunistically available at some call sites — see corpus_index.py.)
Files are written to temp paths and renamed on close() so a crash leaves no
truncated output. Structurally satisfies cicada's GraphSink.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from cobble.file_location import to_json_value
from cobble.interpreter.project.graph_types import GraphEdge, GraphNode, NodeKind

if TYPE_CHECKING:
    from cobble.corpus_index import CorpusIndex


class GraphWriter:
    def __init__(self, nodes_path: Path, edges_path: Path, corpus_index: "CorpusIndex") -> None:
        self._corpus_index = corpus_index
        self._node_seen: set[tuple[NodeKind, str]] = set()
        self._edge_seen: set[tuple] = set()
        self._ntmp = nodes_path.with_suffix(nodes_path.suffix + ".tmp")
        self._etmp = edges_path.with_suffix(edges_path.suffix + ".tmp")
        self._nodes_path = nodes_path
        self._edges_path = edges_path
        self._nf = self._ntmp.open("w")
        self._ef = self._etmp.open("w")

    def add_node(self, node: GraphNode) -> None:
        key = (node.kind, node.id)
        if key in self._node_seen:
            return
        self._node_seen.add(key)
        self._nf.write(
            json.dumps(
                {
                    "id": node.id,
                    "kind": node.kind.value,
                    "file_path": node.file_path,
                    "attrs": node.attrs,
                }
            )
            + "\n"
        )

    def add_edge(self, edge: GraphEdge) -> None:
        # A defensive fallback: an edge whose endpoints were never explicitly
        # add_node'd still yields those nodes, resolved via the same
        # corpus_index as every real construction site, so this can never
        # under-resolve relative to an explicit add_node for the same key.
        self.add_node(GraphNode(
            id=edge.source, kind=edge.source_kind,
            file_path=to_json_value(self._corpus_index.resolve_file_path(edge.source_kind, edge.source)),
        ))
        self.add_node(GraphNode(
            id=edge.target, kind=edge.target_kind,
            file_path=to_json_value(self._corpus_index.resolve_file_path(edge.target_kind, edge.target)),
        ))
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
        self._nf.close()
        self._ef.close()
        self._ntmp.rename(self._nodes_path)
        self._etmp.rename(self._edges_path)

    def __enter__(self) -> "GraphWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
