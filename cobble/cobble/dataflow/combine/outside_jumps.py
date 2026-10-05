"""OutsideJumps — what programs outside a linked set say about jumping into it."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True)
class OutsideJumps:
    known_into: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    unresolved: int = 0
    without_results: tuple[str, ...] = ()
