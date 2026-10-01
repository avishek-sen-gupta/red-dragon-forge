"""NodeKey — how a node of the merged graph is identified everywhere it is keyed.

merge_graph() keys its networkx graph by (kind, id); layout and the renderers
index straight back out with the same pair. The shape is worth naming rather
than passing around as a bare tuple: a Mapping keyed by it is not
interchangeable with one keyed by Hashable, and the name is what stops a
position map and an arbitrary dict being confused for one another.

Its own module, rather than merge.py, so a consumer that only needs to say
what it is keyed by does not have to import the graph-building code.
"""

from __future__ import annotations

from typing import TypeAlias

from cobble.knowledge_graph.graph_types import NodeKind

NodeKey: TypeAlias = tuple[NodeKind, str]
