"""CICS-owned COBOL statement types, relocated from RedDragon (red-dragon
commit b54471dc's DialectParser migration) — RedDragon itself now has zero
CICS-specific type names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from port.cics.cics_visitor import CicsOperand, parse_exec_cics_text


@dataclass(frozen=True)
class ExecCicsStatement:
    """EXEC CICS verb-with-options block."""

    verb: str
    options: dict[str, "CicsOperand | None"]

    def to_dict(self) -> dict:
        # Serialised for informational round-trip only (see RedDragon's
        # to_dict() convention) — parity, not exercised by the AST cache path.
        serialised: dict[str, Any] = {}
        for key, operand in self.options.items():
            if operand is None:
                serialised[key] = None
            else:
                serialised[key] = {
                    "text": operand.text,
                    "is_literal": operand.is_literal,
                }
        return {"type": "EXEC_CICS", "verb": self.verb, "options": serialised}


class CicsDialectParser:
    """Constructs ExecCicsStatement from raw EXEC CICS bridge JSON."""

    def applies(self, data: dict) -> bool:
        return data.get("type") == "EXEC_CICS"

    def parse(self, data: dict) -> ExecCicsStatement:
        text = re.sub(
            r"\*>.*", "", data.get("exec_cics_text", ""), flags=re.MULTILINE
        ).strip()
        verb, options = parse_exec_cics_text(text)
        return ExecCicsStatement(verb=verb, options=options)
