from cobble.cics.statements import ExecCicsStatement
from cobble.cics.verb_source_asg import asg_dialect_parsers
from cobble.interpreter.cobol import cobol_statements
from cobble.sql.statements import ExecSqlStatement


def _parse_under_production_dialects(data: dict):
    """Parse one bridge statement dict with the dialect parsers the ASG walk uses."""
    token = cobol_statements._dialect_parsers.set(asg_dialect_parsers())
    try:
        return cobol_statements.parse_statement(data)
    finally:
        cobol_statements._dialect_parsers.reset(token)


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
