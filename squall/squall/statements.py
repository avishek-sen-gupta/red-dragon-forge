"""SQL-owned COBOL statement types, relocated from RedDragon (red-dragon
commit b54471dc's DialectParser migration) — RedDragon itself now has zero
SQL-specific type names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecSqlStatement:
    """EXEC SQL block. Carries the raw EXEC SQL text verbatim — including the
    EXEC SQL/END-EXEC envelope — exactly as the ProLeap bridge emits it. Squall's
    own strategy treats the body as opaque text: envelope removal and SQL
    parsing are done by squall.parser's grammar-based parser, never by string
    surgery here."""

    text: str

    def to_dict(self) -> dict:
        return {"type": "EXEC_SQL", "text": self.text}


class SqlDialectParser:
    """Constructs ExecSqlStatement from EXEC SQL JSON, from either producer.

    Two feed it and they name the text differently: the ProLeap bridge emits
    ``exec_sql_text`` on a first parse, and ``ExecSqlStatement.to_dict`` writes
    ``text`` thereafter. Reading only the bridge's key recovered nothing from a
    cached ASG -- and cobble's cache IS ``CobolASG.to_dict()``, so every stage
    after the parse saw an empty statement.
    """

    def applies(self, data: Mapping[str, str]) -> bool:
        return data.get("type") == "EXEC_SQL"

    def parse(self, data: Mapping[str, str]) -> ExecSqlStatement:
        return ExecSqlStatement(
            text=data.get("exec_sql_text") or data.get("text") or ""
        )
