"""Everything the page is drawn from: CodeQL's graph and each query's path steps."""

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.experimental.codeql.demo.drawn_edge import DrawnEdge
from cobble.experimental.codeql.demo.edge_row import EdgeRow
from cobble.experimental.codeql.demo.node_row import NodeRow
from cobble.experimental.codeql.demo.step_row import StepRow


@dataclass(frozen=True)
class DemoResults:
    nodes: tuple[NodeRow, ...]
    edges: tuple[EdgeRow, ...]
    flows: Mapping[DrawnEdge, tuple[StepRow, ...]]
