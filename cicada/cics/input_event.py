"""An inbound terminal event: the attention identifier, field values and cursor."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cics.screen.cursor import NO_CURSOR, CursorPosition

DFHENTER = "\x7d"


@dataclass(frozen=True)
class InputEvent:
    eibaid: str = DFHENTER
    fields: Mapping[str, str] = field(default_factory=dict)
    cursor: CursorPosition = NO_CURSOR
