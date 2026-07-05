from squall.statements import ExecSqlStatement, SqlDialectParser


class TestSqlDialectParser:
    def test_applies_to_exec_sql_type(self):
        assert SqlDialectParser().applies({"type": "EXEC_SQL"}) is True

    def test_does_not_apply_to_other_types(self):
        assert SqlDialectParser().applies({"type": "EXEC_CICS"}) is False

    def test_parse_carries_text_verbatim(self):
        data = {
            "type": "EXEC_SQL",
            "exec_sql_text": "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT END-EXEC",
        }
        stmt = SqlDialectParser().parse(data)
        assert isinstance(stmt, ExecSqlStatement)
        assert stmt.text == data["exec_sql_text"]

    def test_parse_empty_text(self):
        stmt = SqlDialectParser().parse({"type": "EXEC_SQL"})
        assert stmt.text == ""
