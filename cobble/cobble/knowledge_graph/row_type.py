"""Which half of the graph one line of a graph file holds."""

from enum import StrEnum


class RowType(StrEnum):
    NODE = "node"
    EDGE = "edge"
