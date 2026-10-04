"""ExecSqlPayload -- one EXEC SQL statement's JSON, from the bridge or the ASG cache."""

from __future__ import annotations

from cobol_asg.source_span import SourceSpan
from pydantic import BaseModel, ConfigDict
from squall.parser.sql_model import Kind, WheneverCondition

NO_POSITION = SourceSpan(0, 0, 0, 0)

_POSITION_FIELDS = frozenset({"line_start", "col_start", "line_end", "col_end"})


class ExecSqlPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    exec_sql_text: str = ""
    text: str = ""
    whenever_condition: WheneverCondition = WheneverCondition.NONE
    whenever_goto: str = ""
    sql_kind: Kind = Kind.GENERIC
    line_start: int = 0
    col_start: int = 0
    line_end: int = 0
    col_end: int = 0

    def sql(self) -> str:
        return self.exec_sql_text or self.text

    def is_cached(self) -> bool:
        return "whenever_condition" in self.model_fields_set

    def at(self, span: SourceSpan) -> ExecSqlPayload:
        return self.model_copy(
            update={
                "line_start": span.line_start,
                "col_start": span.col_start,
                "line_end": span.line_end,
                "col_end": span.col_end,
            }
        )

    def span(self) -> SourceSpan:
        if not self.model_fields_set >= _POSITION_FIELDS:
            return NO_POSITION
        return SourceSpan(self.line_start, self.col_start, self.line_end, self.col_end)
