"""A PERFORM range whose entry the state marks, and the call sites that enter it, in the order their marks number them."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind
from cobble.experimental.horn.context import Context, performed


@dataclass(frozen=True)
class Entries:
    range: Context
    calls: tuple[str, ...]

    def value(self, call: str) -> int:
        if call not in self.calls:
            raise ValueError(f"{call} does not enter {self.range}")
        return 1 + self.calls.index(call)


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
