"""Unit tests for CicsDialectParser — relocated from RedDragon's
test_exec_cics_comment_strip.py (red-dragon-kn0n); now exercises the real
dialect-parser mechanism instead of the removed _cics_text_parser contextvar."""

from __future__ import annotations

from cics.statements import CicsDialectParser, CicsOperand, ExecCicsStatement


class TestCicsDialectParserApplies:
    def test_applies_to_exec_cics_type(self):
        assert CicsDialectParser().applies({"type": "EXEC_CICS"}) is True

    def test_does_not_apply_to_other_types(self):
        assert CicsDialectParser().applies({"type": "EXEC_SQL"}) is False
        assert CicsDialectParser().applies({}) is False


class TestCicsDialectParserCommentStrip:
    def test_inline_comment_stripped_before_parser(self):
        """*> inline comment is stripped from exec_cics_text before parsing.

        Note: parse_exec_cics_text's grammar requires the full 'EXEC CICS ...
        END-EXEC' envelope (its own docstring: "Parse 'EXEC CICS VERB
        OPT(val) FLAG END-EXEC'") — real ProLeap bridge output includes it;
        the original RedDragon test used a FAKE parser and so never needed
        grammatically valid text, only exercising the comment-strip regex in
        isolation. This rewrite calls the REAL parser, so the fixture text
        must be real, envelope-included EXEC CICS syntax.
        """
        stmt = CicsDialectParser().parse(
            {
                "exec_cics_text": "EXEC CICS RETURN TRANSID (WS-TRANID) END-EXEC *> some comment",
                "type": "EXEC_CICS",
            }
        )
        assert stmt.verb == "RETURN"

    def test_multiline_comment_stripped(self):
        """*> comment on its own line is stripped; remaining lines are joined."""
        stmt = CicsDialectParser().parse(
            {
                "exec_cics_text": (
                    "EXEC CICS RETURN TRANSID (WS-TRANID)\n*> a trailing comment\nEND-EXEC"
                ),
                "type": "EXEC_CICS",
            }
        )
        assert stmt.verb == "RETURN"

    def test_cotrn02c_pattern_no_valueerror(self):
        """Reproduces the exact COTRN02C exec_cics_text shape that raised ValueError (kn0n)."""
        # No exception = pass
        CicsDialectParser().parse(
            {
                "exec_cics_text": (
                    "EXEC CICS RETURN TRANSID (WS-TRANID) COMMAREA (CARDDEMO-COMMAREA)"
                    " *>  LENGTH(LENGTH OF CARDDEMO-COMMAREA)\nEND-EXEC"
                ),
                "type": "EXEC_CICS",
            }
        )


class TestExecCicsStatementRelocatedShape:
    def test_from_dict_via_dialect_parser_returns_exec_cics_statement(self):
        stmt = CicsDialectParser().parse(
            {
                "exec_cics_text": "EXEC CICS SEND MAP ('TRNADD') END-EXEC",
                "type": "EXEC_CICS",
            }
        )
        assert isinstance(stmt, ExecCicsStatement)
        assert stmt.verb == "SEND MAP"

    def test_cics_operand_shape_unchanged(self):
        operand = CicsOperand(text="X", is_literal=True)
        assert operand.text == "X"
        assert operand.is_literal is True
        assert operand.subscripts == ()
