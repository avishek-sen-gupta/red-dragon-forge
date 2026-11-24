"""One step of a dataflow path, from one node of a program's graph to another."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StepRow:
    program: str
    source: str
    target: str
