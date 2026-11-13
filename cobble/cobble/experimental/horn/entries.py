"""A PERFORM range whose entry the state marks, and the call sites that enter it, in the order their marks number them."""

from dataclasses import dataclass

import z3
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind
from cobble.experimental.horn.context import Context, performed
from cobble.experimental.horn.terms import constant


@dataclass(frozen=True)
class Entries:
    range: Context
    calls: tuple[str, ...]

    @property
    def width(self) -> int:
        """Bytes enough to number every call site after 0, which means not yet
        entered."""
        return (len(self.calls).bit_length() + 7) // 8 or 1

    def value(self, call: str) -> z3.BitVecRef:
        if call not in self.calls:
            raise ValueError(f"{call} does not enter {self.range}")
        return constant((1 + self.calls.index(call)).to_bytes(self.width, "big"))

    def unset(self) -> z3.BitVecRef:
        return constant(bytes(self.width))


def entries_of(cfg: Cfg, range_: Context) -> Entries:
    return Entries(
        range_,
        tuple(
            sorted(
                edge.source
                for edge in cfg.edges
                if edge.kind is EdgeKind.PERFORM and performed(cfg, edge) == range_
            )
        ),
    )
