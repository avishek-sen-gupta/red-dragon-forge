"""Unit tests for CicsDialectParser — relocated from RedDragon's
test_exec_cics_comment_strip.py (red-dragon-kn0n); now exercises the real
dialect-parser mechanism instead of the removed _cics_text_parser contextvar."""

from __future__ import annotations

from cics.statements import CicsDialectParser, CicsOperand, ExecCicsStatement
from cobol_asg.source_span import SourceSpan

_POSITION = ("line_start", "col_start", "line_end", "col_end")


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


class TestExecCicsStatementRoundTrip:
    """``to_dict`` is not informational here: cobble's parsed-ASG cache IS
    ``CobolASG.to_dict()``, so a key dropped on the way out is one no consumer can
    recover. It used to drop an operand's subscripts, and a subscripted callee then
    read back as a scalar."""

    def test_a_subscripted_operand_survives_the_round_trip(self):
        statement = CicsDialectParser().parse(
            {
                "exec_cics_text": (
                    "EXEC CICS XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION))"
                    " COMMAREA(CARDDEMO-COMMAREA) END-EXEC"
                ),
                "type": "EXEC_CICS",
            }
        )

        assert ExecCicsStatement.from_dict(statement.to_dict()) == statement

    def test_a_reference_modified_operand_survives_the_round_trip(self):
        statement = CicsDialectParser().parse(
            {
                "exec_cics_text": "EXEC CICS SEND FROM(WS-AREA(2:3)) END-EXEC",
                "type": "EXEC_CICS",
            }
        )

        assert ExecCicsStatement.from_dict(statement.to_dict()) == statement

    def test_the_bridge_position_survives_parsing_and_the_round_trip(self):
        statement = CicsDialectParser().parse(
            {
                "exec_cics_text": "EXEC CICS RETURN TRANSID(WS-TRANID) END-EXEC",
                "type": "EXEC_CICS",
                "line_start": 479,
                "col_start": 6,
                "line_end": 483,
                "col_end": 13,
            }
        )

        assert statement.span == SourceSpan(479, 6, 483, 13)
        assert {k: statement.to_dict()[k] for k in _POSITION} == {
            "line_start": 479,
            "col_start": 6,
            "line_end": 483,
            "col_end": 13,
        }
        assert ExecCicsStatement.from_dict(statement.to_dict()) == statement

    def test_a_plain_operand_still_serializes_to_the_two_keys_it_always_did(self):
        statement = ExecCicsStatement(
            verb="XCTL",
            options={"PROGRAM": CicsOperand(text="CDEMO-TO-PROGRAM", is_literal=False)},
        )

        assert statement.to_dict() == {
            "type": "EXEC_CICS",
            "verb": "XCTL",
            "options": {"PROGRAM": {"text": "CDEMO-TO-PROGRAM", "is_literal": False}},
        }

    def test_a_bare_flag_stays_a_key_with_no_operand_behind_it(self):
        statement = ExecCicsStatement(
            verb="INQUIRE",
            options={
                "PROGRAM": CicsOperand(text="WS-PROG", is_literal=False),
                "NOHANDLE": None,
            },
        )

        assert ExecCicsStatement.from_dict(statement.to_dict()) == statement

    def test_a_payload_written_before_the_structure_existed_still_reads(self):
        statement = ExecCicsStatement.from_dict(
            {
                "type": "EXEC_CICS",
                "verb": "LINK",
                "options": {"PROGRAM": {"text": "WS-PROG", "is_literal": False}},
            }
        )

        assert statement.options["PROGRAM"] == CicsOperand(
            text="WS-PROG", is_literal=False
        )
