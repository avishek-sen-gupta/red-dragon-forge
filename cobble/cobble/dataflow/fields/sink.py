"""Where a program's bytes go when they leave it: the sink's kind and name."""

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.fields.sink_kind import SinkKind


@dataclass(frozen=True)
class Sink:
    """A sink; `text()` is for ids and display only, `wire()` is what artifacts carry."""

    kind: SinkKind
    name: str

    def text(self) -> str:
        return f"{self.kind}:{self.name}" if self.name else str(self.kind)

    def wire(self) -> Mapping[str, str]:
        return {"kind": str(self.kind), "name": self.name}

    @property
    def is_none(self) -> bool:
        return self.kind is SinkKind.NONE


NO_SINK = Sink(SinkKind.NONE, "")
