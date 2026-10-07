"""One step of the fixpoint's worklist walk, as a diagnostic sees it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.fields.state import State


@dataclass(frozen=True)
class Stepped:
    """The node a step took, the entry states before and after it, and what is left."""

    node: str
    before: Mapping[str, State]
    after: Mapping[str, State]
    queued: int
    dequeues: int
