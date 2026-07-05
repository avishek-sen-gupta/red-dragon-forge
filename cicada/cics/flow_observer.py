from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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


def field_direction(field: BmsField) -> str:
    """Return "input" for unprotected fields, "output" for protected/auto-skip."""
    protected = {"PROT", "ASKIP"}
    if any(a.upper() in protected for a in field.attrb):
        return "output"
    return "input"
