"""One reachability state: a node, and the resume points of the PERFORMs open there."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReachState:
    node: str
    stack: tuple[str, ...]
