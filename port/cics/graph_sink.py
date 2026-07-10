"""GraphSink — the streaming node/edge consumer the CICS flow extractor emits into.

Defined here (cicada-local) rather than importing knowledge_graph's GraphWriter:
Protocols are structural, so any object with add_node/add_edge (e.g. the KG
GraphWriter) satisfies it, and the import-linter contract forbidding
cics -> knowledge_graph is respected. Vocabulary types come from the shared
interpreter.project.graph_types leaf.
"""

from __future__ import annotations

from typing import Protocol

from port.interpreter.project.graph_types import GraphEdge, GraphNode


class GraphSink(Protocol):
    def add_node(self, node: GraphNode) -> None: ...
    def add_edge(self, edge: GraphEdge) -> None: ...
