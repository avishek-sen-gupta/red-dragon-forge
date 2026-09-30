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

    def test_the_statement_survives_a_round_trip_through_the_cache(self):
        """cobble's parsed-ASG cache IS CobolASG.to_dict(), and every stage after
        the parse reads that JSON rather than the source. to_dict() writes `text`
        while the bridge emits `exec_sql_text`, so a reader that knows only the
        bridge's key recovers nothing from a cached ASG."""
        stmt = ExecSqlStatement(
            text="EXEC SQL WHENEVER SQLERROR GO TO ERR-PARA END-EXEC"
        )

        assert SqlDialectParser().parse(stmt.to_dict()) == stmt
