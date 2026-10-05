"""Jump — one jumps.jsonl row: where control goes and what it hands over."""

from dataclasses import dataclass, field

from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind


@dataclass(frozen=True)
class Jump:
    program: str
    node: str
    line: int
    kind: JumpKind
    returns: bool
    target: Fact = field(default_factory=Fact)
    transid: Fact = field(default_factory=Fact)
    areas: tuple[JumpArea, ...] = field(default_factory=tuple)
