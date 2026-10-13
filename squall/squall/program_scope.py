"""What the SQL lowering knows about the program it is lowering: cursor declarations and VARCHAR groups."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from squall.parser.sql_model import FieldMeta


@dataclass(frozen=True)
class ProgramScope:
    declarations: Mapping[str, str] = field(default_factory=dict)
    varchar: Mapping[str, FieldMeta] = field(default_factory=dict)

    def declaring(self, cursor: str, text: str) -> ProgramScope:
        return ProgramScope({**self.declarations, cursor: text}, self.varchar)
