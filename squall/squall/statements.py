"""SQL-owned COBOL statement types, relocated from RedDragon (red-dragon
commit b54471dc's DialectParser migration) — RedDragon itself now has zero
SQL-specific type names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cobol_asg.source_span import SourceSpan
from squall.exec_sql_payload import NO_POSITION, ExecSqlPayload
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
    span: SourceSpan = NO_POSITION

    def to_dict(self) -> dict:
        """Flat, and always both directive keys; the four position keys only when
        the bridge reported a position.

        cobble's ASG cache IS this dict, and re-deriving the directive on every
        read would run the SQL grammar for every statement of every member in
        every stage. Written through ExecSqlPayload, the model parse() reads it
        back into, so the two directions cannot disagree about a key.
        """
        payload = ExecSqlPayload(
            text=self.text,
            whenever_condition=self.whenever_condition,
            whenever_goto=_goto_target(self.whenever_action),
            sql_kind=self.kind,
        )
        located = payload if self.span == NO_POSITION else payload.at(self.span)
        return {
            "type": "EXEC_SQL",
            **located.model_dump(mode="json", exclude_unset=True),
        }


class SqlDialectParser:
    """Constructs ExecSqlStatement from EXEC SQL JSON, from either producer.

    Two feed it and they name the text differently: the ProLeap bridge emits
    ``exec_sql_text`` on a first parse, and ``ExecSqlStatement.to_dict`` writes
    ``text`` thereafter. Reading only the bridge's key recovered nothing from a
    cached ASG -- and cobble's cache IS ``CobolASG.to_dict()``, so every stage
    after the parse saw an empty statement.
    """

    def applies(self, data: Mapping[str, str | int]) -> bool:
        return data.get("type") == "EXEC_SQL"

    def parse(self, data: Mapping[str, str | int]) -> ExecSqlStatement:
        payload = ExecSqlPayload.model_validate(data)
        if payload.is_cached():
            return _from_cache(payload)
        return _from_source(payload.sql(), payload.span())


def _goto_target(action: WheneverAction) -> str:
    """A GoTo's label; empty for the two actions that name none."""
    match action:
        case GoTo(target=target):
            return target
        case _:
            return ""


def _from_cache(payload: ExecSqlPayload) -> ExecSqlStatement:
    condition = payload.whenever_condition
    return ExecSqlStatement(
        payload.sql(),
        condition,
        _cached_action(condition, payload.whenever_goto),
        payload.sql_kind,
        payload.span(),
    )


def _cached_action(condition: WheneverCondition, target: str) -> WheneverAction:
    """CONTINUE and "no directive" both name no label, and the condition tells
    them apart: only a real directive carries one."""
    if target:
        return GoTo(target)
    if condition is WheneverCondition.NONE:
        return NoOpAction()
    return Continue()


def _from_source(text: str, span: SourceSpan) -> ExecSqlStatement:
    plan = parse_exec_sql(text)
    return ExecSqlStatement(
        text, plan.whenever_condition, plan.whenever_action, plan.kind, span
    )
