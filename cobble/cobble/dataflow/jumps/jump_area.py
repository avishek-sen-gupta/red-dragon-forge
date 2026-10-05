"""JumpArea — one block of memory a jump hands over, field by field."""

from dataclasses import dataclass, field

from cobble.dataflow.jumps.fact import Fact


@dataclass(frozen=True)
class JumpArea:
    param: int
    extent: str
    fields: tuple[Fact, ...] = field(default_factory=tuple)
