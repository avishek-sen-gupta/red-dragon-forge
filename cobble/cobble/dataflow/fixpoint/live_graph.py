"""What backward liveness needs of one program, and nothing of its ASG: small, and picklable."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.transfer import Write


@dataclass(frozen=True)
class LiveGraph:
    """Node ids in CFG order, edges as positions into it, and each node's writes."""

    order: tuple[str, ...]
    successors: tuple[tuple[int, ...], ...]
    predecessors: tuple[tuple[int, ...], ...]
    writes: tuple[tuple[Write, ...], ...]
