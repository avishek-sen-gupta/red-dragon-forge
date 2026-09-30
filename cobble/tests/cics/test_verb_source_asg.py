from cobble.cics.asg_dialect_scope import asg_dialect_parsers_registered
from cics.statements import ExecCicsStatement
from cobble.cics.verb_source_asg import _statement_to_verb
from cobol_asg import cobol_statements
from cobol_asg.cobol_statements import CobolStatementType
from squall.statements import ExecSqlStatement, Kind


def _parse_under_production_dialects(data: dict) -> CobolStatementType:
    """Parse one bridge statement dict with the dialect parsers the ASG walk uses."""
    with asg_dialect_parsers_registered():
        return cobol_statements.parse_statement(data)


def test_exec_sql_parses_instead_of_raising() -> None:
    text = "EXEC SQL SELECT ACCT_ID INTO :WS-ACCT FROM ACCTDAT END-EXEC"
    stmt = _parse_under_production_dialects({"type": "EXEC_SQL", "exec_sql_text": text})
    assert stmt == ExecSqlStatement(text=text, kind=Kind.SELECT_INTO)


def test_exec_cics_still_parses() -> None:
    stmt = _parse_under_production_dialects(
        {"type": "EXEC_CICS", "exec_cics_text": "EXEC CICS RETURN END-EXEC"}
    )
    assert isinstance(stmt, ExecCicsStatement)
    assert stmt.verb == "RETURN"


def _verb_fields(text: str, data_fields=()) -> tuple:
    """The verb one EXEC CICS statement becomes, or () when it becomes none."""
    stmt = _parse_under_production_dialects(
        {"type": "EXEC_CICS", "exec_cics_text": text}
    )
    assert isinstance(stmt, ExecCicsStatement)
    match _statement_to_verb(stmt, "SOMEPROG", list(data_fields)):
        case None:
            return ()
        case verb:
            return (verb.verb, verb.program, verb.transid)


def test_start_transid_becomes_a_verb_the_graph_reads() -> None:
    """START is the third way a program names another unit of work, after XCTL and
    RETURN TRANSID, and the only asynchronous one. The builder table had no entry
    for it, so every EXEC CICS START was parsed and dropped."""
    assert _verb_fields(
        "EXEC CICS START TRANSID('A123') INTERVAL(000500) END-EXEC"
    ) == ("START_TRANSID", "SOMEPROG", "A123")


def test_a_start_with_no_transid_is_not_a_graph_event() -> None:
    """START TRANSID is optional in the API. With no transaction named there is
    nothing for the graph to point at -- the same rule RETURN already follows."""
    assert _verb_fields("EXEC CICS START TERMID(EIBTRMID) END-EXEC") == ()
