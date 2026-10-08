"""The program a call hands its areas to, as far as the source names it."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.area_kind import AreaKind


@dataclass(frozen=True)
class CallSite:
    """``callee`` is empty when the call names its program by a data item."""

    callee: str
    kind: AreaKind

    @property
    def dynamic(self) -> bool:
        return not self.callee
