"""One edge of CodeQL's graph, between two nodes of one program."""

from dataclasses import dataclass

from cobble.experimental.codeql.demo.drawn_edge import DrawnEdge


@dataclass(frozen=True)
class EdgeRow:
    program: str
    source: str
    target: str
    kind: DrawnEdge
