from squall.statements import (
    Continue,
    ExecSqlStatement,
    GoTo,
    Kind,
    NoOpAction,
    SqlDialectParser,
    WheneverCondition,
)


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

    def test_a_whenever_directive_is_typed_on_the_statement(self):
        """The directive is what cobble's CFG needs and what strategy re-parsed
        on every lowering. Parsed once, here at the ASG boundary."""
        stmt = SqlDialectParser().parse(
            {
                "type": "EXEC_SQL",
                "exec_sql_text": "EXEC SQL WHENEVER NOT FOUND GO TO NF-PARA END-EXEC",
            }
        )

        assert stmt.whenever_condition == WheneverCondition.NOT_FOUND
        assert stmt.whenever_action == GoTo("NF-PARA")

    def test_a_non_directive_statement_carries_the_null_objects(self):
        stmt = SqlDialectParser().parse(
            {
                "type": "EXEC_SQL",
                "exec_sql_text": "EXEC SQL SELECT A INTO :B FROM T END-EXEC",
            }
        )

        assert stmt.whenever_condition == WheneverCondition.NONE
        assert stmt.whenever_action == NoOpAction()

    def test_the_directive_survives_the_cache_without_reparsing(self):
        """Serialised flat, so a cache read reconstructs it instead of running the
        grammar again for every SQL statement of every member on every stage."""
        stmt = SqlDialectParser().parse(
            {
                "type": "EXEC_SQL",
                "exec_sql_text": "EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC",
            }
        )

        assert SqlDialectParser().parse(stmt.to_dict()) == stmt
        assert stmt.whenever_action == Continue()

    def test_the_statement_kind_is_carried_and_survives_the_cache(self):
        """What the CFG labels a node with. GENERIC is the null object the parser
        already returns for text it cannot classify, so an unparseable block keeps
        the label it had rather than inventing one."""
        select = SqlDialectParser().parse(
            {
                "type": "EXEC_SQL",
                "exec_sql_text": "EXEC SQL SELECT A INTO :B FROM T END-EXEC",
            }
        )
        garbage = SqlDialectParser().parse(
            {"type": "EXEC_SQL", "exec_sql_text": "EXEC SQL NOT SQL END-EXEC"}
        )

        assert select.kind == Kind.SELECT_INTO
        assert garbage.kind == Kind.GENERIC
        assert SqlDialectParser().parse(select.to_dict()) == select
