"""SQL-owned COBOL statement types, relocated from RedDragon (red-dragon
commit b54471dc's DialectParser migration) — RedDragon itself now has zero
SQL-specific type names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import (
    Continue,
    GoTo,
    Kind,
    NoOpAction,
    WheneverAction,
    WheneverCondition,
)

__all__ = [
    "Continue",
    "ExecSqlStatement",
    "GoTo",
    "Kind",
    "NoOpAction",
    "SqlDialectParser",
    "WheneverAction",
    "WheneverCondition",
]


@dataclass(frozen=True)
class ExecSqlStatement:
    """EXEC SQL block. Carries the raw EXEC SQL text verbatim — including the
    EXEC SQL/END-EXEC envelope — exactly as the ProLeap bridge emits it. Squall's
    own strategy treats the body as opaque text: envelope removal and SQL
    parsing are done by squall.parser's grammar-based parser, never by string
    surgery here."""

    text: str
    whenever_condition: WheneverCondition = WheneverCondition.NONE
    whenever_action: WheneverAction = field(default_factory=NoOpAction)
    kind: Kind = Kind.GENERIC

    def to_dict(self) -> dict:
        """Flat, string-valued, and always both directive keys.

        cobble's ASG cache IS this dict, and re-deriving the directive on every
        read would run the SQL grammar for every statement of every member in
        every stage. Written flat rather than as a nested object so the whole
        statement stays a Mapping[str, str] for whoever reads it back.
        """
        return {
            "type": "EXEC_SQL",
            "text": self.text,
            "whenever_condition": self.whenever_condition.value,
            "whenever_goto": _goto_target(self.whenever_action),
            "sql_kind": self.kind.value,
        }


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
        text = data.get("exec_sql_text") or data.get("text") or ""
        if "whenever_condition" in data:
            return _from_cache(text, data)
        return _from_source(text)


def _goto_target(action: WheneverAction) -> str:
    """A GoTo's label; empty for the two actions that name none."""
    match action:
        case GoTo(target=target):
            return target
        case _:
            return ""


def _from_cache(text: str, data: Mapping[str, str]) -> ExecSqlStatement:
    condition = WheneverCondition(data.get("whenever_condition") or "none")
    target = data.get("whenever_goto") or ""
    return ExecSqlStatement(
        text,
        condition,
        _cached_action(condition, target),
        Kind(data.get("sql_kind") or Kind.GENERIC.value),
    )


def _cached_action(condition: WheneverCondition, target: str) -> WheneverAction:
    """CONTINUE and "no directive" both name no label, and the condition tells
    them apart: only a real directive carries one."""
    if target:
        return GoTo(target)
    if condition is WheneverCondition.NONE:
        return NoOpAction()
    return Continue()


def _from_source(text: str) -> ExecSqlStatement:
    plan = parse_exec_sql(text)
    return ExecSqlStatement(
        text, plan.whenever_condition, plan.whenever_action, plan.kind
    )
