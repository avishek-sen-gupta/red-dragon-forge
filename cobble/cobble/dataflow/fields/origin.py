"""A non-storage origin of a written value: its kind, its name, and any target left unplaced."""

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.fields.origin_kind import OriginKind


@dataclass(frozen=True)
class Origin:
    """An origin; `text()` is for ids and display only, `wire()` is what artifacts carry."""

    kind: OriginKind
    name: str
    unplaced: str = ""

    def text(self) -> str:
        return f"{self.kind}:{self.name}" if self.name else str(self.kind)

    def wire(self) -> Mapping[str, str]:
        named = {"kind": str(self.kind), "name": self.name}
        return {**named, "unplaced": self.unplaced} if self.unplaced else named

    @property
    def is_storage(self) -> bool:
        return self.kind is OriginKind.NONE


NO_ORIGIN = Origin(OriginKind.NONE, "")
