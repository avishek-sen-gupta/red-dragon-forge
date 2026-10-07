"""What the diagnostic keeps of one step: small enough to hold for every step."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cobble.dataflow.fields.state import State


@dataclass(frozen=True)
class StepFact:
    """The node taken, what it grew, a timeline row when due, and the final states
    only on the last step -- every earlier step's states are let go as it passes."""

    node: str
    grew: tuple[str, ...]
    fields: tuple[str, ...]
    queued: int
    snapshot: str = ""
    final: Mapping[str, State] = MappingProxyType({})
