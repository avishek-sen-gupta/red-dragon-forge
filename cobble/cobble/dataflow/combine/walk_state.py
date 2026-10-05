"""WalkState — one step of a reachability walk: what it has seen, what is next, what it found."""

from dataclasses import dataclass
from typing import Generic, TypeVar

_V = TypeVar("_V")
_C = TypeVar("_C")


@dataclass(frozen=True)
class WalkState(Generic[_V, _C]):
    seen: frozenset[_V]
    frontier: frozenset[_V]
    found: _C
    revisited: bool = False
