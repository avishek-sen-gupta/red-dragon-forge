from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bms_copybook_gen.models import BmsField


@dataclass(frozen=True)
class CicsVerb:
    verb: str
    program: str
    map_name: str | None
    mapset_name: str | None
    xctl_target: str | None
    transid: str | None


class CicsFlowObserver(Protocol):
    def on_verb(self, verb: CicsVerb) -> None: ...


class NullCicsFlowObserver:
    def on_verb(self, verb: CicsVerb) -> None:
        pass
