"""SQL-owned COBOL statement types, ported from Squall (squall/statements.py,
itself relocated from RedDragon at red-dragon commit b54471dc's DialectParser
migration) — RedDragon itself has zero SQL-specific type names.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecSqlStatement:
    """EXEC SQL block. Carries the raw EXEC SQL text verbatim — including the
    EXEC SQL/END-EXEC envelope — exactly as the ProLeap bridge emits it. The
    body is opaque here: the graph does not read the SQL, so nothing in this
    port removes the envelope or parses the statement.
    """

    text: str

    def to_dict(self) -> dict:
        return {"type": "EXEC_SQL", "text": self.text}


class SqlDialectParser:
    """Constructs ExecSqlStatement from raw EXEC SQL bridge JSON."""

    def applies(self, data: dict) -> bool:
        return data.get("type") == "EXEC_SQL"

    def parse(self, data: dict) -> ExecSqlStatement:
        return ExecSqlStatement(text=data.get("exec_sql_text", "") or "")
