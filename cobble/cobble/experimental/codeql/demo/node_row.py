"""One node of CodeQL's graph: its program, its id there, what it is drawn as and its label."""

from dataclasses import dataclass

from cobble.experimental.codeql.demo.drawn_kind import DrawnKind


@dataclass(frozen=True)
class NodeRow:
    program: str
    node: str
    kind: DrawnKind
    label: str
