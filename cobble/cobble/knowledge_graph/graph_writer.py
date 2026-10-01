"""GraphWriter — streaming sink for the knowledge graph.

Nodes and edges stream to one .jsonl file, each row tagged with which it is
(see graph_file), deduped keep-first, on first sighting, with no buffering.
What counts as the same edge depends on its kind -- see ATTRS_ARE_IDENTITY --
because for most kinds the endpoints are the whole claim, while a byte-level
dataflow edge says something different for each extent pair it carries. This
is only correct because a node's location is resolved once, up front, by a
CorpusIndex passed in at construction — every occurrence of a given (kind, id),
whether from an extractor's explicit add_node or add_edge's own defensive
endpoint-stub synthesis, resolves to the same location no matter what order
things arrive in. add_edge writes both endpoints before the edge, so every node
row precedes the first edge row naming it.
The file is written to a temp path and renamed only when the run completes, so
a run that raises leaves its partial rows in the .tmp and nothing at the path.
Opened through ``graph_writer`` rather than the context-manager protocol, whose
``__exit__`` signature the lint rules cannot express. Structurally satisfies
cicada's GraphSink.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from cobble.knowledge_graph.graph_file import edge_row, node_row
from cobble.knowledge_graph.graph_types import (
    ATTRS_ARE_IDENTITY,
    GraphEdge,
    GraphNode,
)
from cobble.sink_state import FirstSighting

if TYPE_CHECKING:
    from cobble.corpus_index import FileLocationResolver


def _edge_key(edge: GraphEdge) -> tuple:
    """What makes this edge a distinct fact, per ATTRS_ARE_IDENTITY.

    Attrs reach the key as canonical JSON because AttrValue admits sequences and
    mappings, so the dict itself is not reliably hashable and its own key order
    is a property of how the producer built it rather than of the fact.
    """
    endpoints = (
        edge.source,
        edge.source_kind,
        edge.target,
        edge.target_kind,
        edge.kind,
    )
    if edge.kind not in ATTRS_ARE_IDENTITY:
        return endpoints
    return (*endpoints, json.dumps(edge.attrs, sort_keys=True))


class GraphWriter:
    def __init__(self, path: Path, corpus_index: FileLocationResolver) -> None:
        self._corpus_index = corpus_index
        # Nodes and edges dedupe separately: the same (kind, id) pair can
        # legitimately appear in both an edge key and a node key.
        self._nodes_written = FirstSighting()
        self._edges_written = FirstSighting()
        self._tmp = path.with_suffix(path.suffix + ".tmp")
        self._path = path
        self._file = self._tmp.open("w")

    def add_node(self, node: GraphNode) -> None:
        if not self._nodes_written.first_time((node.kind, node.id)):
            return
        self._file.write(node_row(node).model_dump_json() + "\n")

    def add_edge(self, edge: GraphEdge) -> None:
        # A defensive fallback: an edge whose endpoints were never explicitly
        # add_node'd still yields those nodes, resolved via the same
        # corpus_index as every real construction site, so this can never
        # under-resolve relative to an explicit add_node for the same key.
        self.add_node(
            GraphNode(
                id=edge.source,
                kind=edge.source_kind,
                location=self._corpus_index.resolve_file_path(
                    edge.source_kind, edge.source
                ),
            )
        )
        self.add_node(
            GraphNode(
                id=edge.target,
                kind=edge.target_kind,
                location=self._corpus_index.resolve_file_path(
                    edge.target_kind, edge.target
                ),
            )
        )
        if not self._edges_written.first_time(_edge_key(edge)):
            return
        self._file.write(edge_row(edge).model_dump_json() + "\n")

    def add_all(self, nodes, edges) -> None:
        for n in nodes:
            self.add_node(n)
        for e in edges:
            self.add_edge(e)

    def close(self) -> None:
        self._file.close()
        self._tmp.rename(self._path)

    def abandon(self) -> None:
        self._file.close()


@contextmanager
def graph_writer(
    path: Path, corpus_index: FileLocationResolver
) -> Iterator[GraphWriter]:
    writer = GraphWriter(path, corpus_index)
    try:
        yield writer
    except BaseException:
        writer.abandon()
        raise
    writer.close()
