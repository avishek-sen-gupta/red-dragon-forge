from squall.statements import ExecSqlStatement, Kind, SqlDialectParser


def test_sql_dialect_parser_applies_to_exec_sql() -> None:
    assert SqlDialectParser().applies({"type": "EXEC_SQL"})


def test_sql_dialect_parser_does_not_apply_to_exec_cics() -> None:
    assert not SqlDialectParser().applies({"type": "EXEC_CICS"})


def test_sql_dialect_parser_carries_the_bridge_text_verbatim() -> None:
    text = "EXEC SQL SELECT ACCT_ID INTO :WS-ACCT FROM ACCTDAT END-EXEC"
    stmt = SqlDialectParser().parse({"type": "EXEC_SQL", "exec_sql_text": text})
    assert stmt == ExecSqlStatement(text=text, kind=Kind.SELECT_INTO)


def test_sql_dialect_parser_tolerates_a_missing_text_key() -> None:
    assert SqlDialectParser().parse({"type": "EXEC_SQL"}) == ExecSqlStatement(text="")


def test_exec_sql_statement_round_trips_to_dict() -> None:
    text = "EXEC SQL COMMIT END-EXEC"
    assert ExecSqlStatement(text=text).to_dict() == {
        "type": "EXEC_SQL",
        "text": text,
        "whenever_condition": "none",
        "whenever_goto": "",
        "sql_kind": "generic",
    }
