"""What a node of CodeQL's graph is drawn as: its kind in the graph, or the file or log statement it is."""

from enum import Enum


class DrawnKind(Enum):
    ASSIGN = "ASSIGN"
    CALL = "CALL"
    TEST = "TEST"
    LABEL = "LABEL"
    NOP = "NOP"
    READ = "READ"
    WRITE = "WRITE"
    REWRITE = "REWRITE"
    DISPLAY = "DISPLAY"
