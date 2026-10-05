"""Linked — the result of linking: targets, the edges used, and the run report."""

from dataclasses import dataclass

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.combine.run_report import RunReport


@dataclass(frozen=True)
class Linked:
    targets: tuple[LinkedTarget, ...]
    edges: tuple[Edge, ...]
    report: RunReport
