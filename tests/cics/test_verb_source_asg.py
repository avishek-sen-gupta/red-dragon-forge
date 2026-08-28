from collections.abc import Mapping

from cobble.cics.asg_dialect_scope import asg_dialect_parsers_registered
from cobble.cics.statements import ExecCicsStatement
from cobble.interpreter.cobol import cobol_statements
from cobble.sql.statements import ExecSqlStatement


def _parse_under_production_dialects(data: Mapping):
    """Parse one bridge statement dict with the dialect parsers the ASG walk uses."""
    with asg_dialect_parsers_registered():
        return cobol_statements.parse_statement(data)


def test_exec_sql_parses_instead_of_raising() -> None:
    text = "EXEC SQL SELECT ACCT_ID INTO :WS-ACCT FROM ACCTDAT END-EXEC"
    stmt = _parse_under_production_dialects({"type": "EXEC_SQL", "exec_sql_text": text})
    assert stmt == ExecSqlStatement(text=text)


def test_exec_cics_still_parses() -> None:
    stmt = _parse_under_production_dialects(
        {"type": "EXEC_CICS", "exec_cics_text": "EXEC CICS RETURN END-EXEC"}
    )
    assert isinstance(stmt, ExecCicsStatement)
    assert stmt.verb == "RETURN"
