"""Tests for shared lexical rules: continuation, terminator, comments, quoting, literals."""

from __future__ import annotations

from pathlib import Path

from lark import Lark
from tests.covers import NotLanguageFeature, covers

# Resolved relative to this test file (not the process cwd) so the test
# passes regardless of whether pytest/the pre-commit hook is invoked from
# the repo root or from jackal/ -- those two invocation contexts disagree
# on what a "jackal/..." relative path means.
_GRAMMAR_PATH = str(
    Path(__file__).resolve().parents[2] / "jackal" / "idcams" / "grammar" / "ams.lark"
)


def _lex(text: str) -> list:
    parser = Lark.open(_GRAMMAR_PATH, start="value", parser="earley")
    return list(parser.parse(text).children)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_quoted_string_with_embedded_comma_and_paren():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse("'A,(B)'\n")
    assert tree.children[0].value == "'A,(B)'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_quoted_string_embedded_doubled_quote_escapes():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse("'IT''S'\n")
    assert tree.children[0].value == "'IT''S'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_hex_literal():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse("X'C1C2C3'\n")
    assert tree.children[0].value == "X'C1C2C3'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_binary_literal():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse("B'0101'\n")
    assert tree.children[0].value == "B'0101'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_semicolon_terminates_and_rest_of_line_is_comment():
    parser = Lark.open(_GRAMMAR_PATH, start="start", parser="earley")
    # SET MAXCC=0 followed by a semicolon-commented remainder, then a real
    # continued command on the next line -- both must parse.
    text = "SET MAXCC=0; ignored garbage $$$ !!!\nCANCEL\n"
    tree = parser.parse(text)
    assert len(tree.children) == 2


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inline_comment_between_keyword_and_value():
    parser = Lark.open(_GRAMMAR_PATH, start="start", parser="earley")
    text = "SET /* comment */ MAXCC=0\n"
    tree = parser.parse(text)
    assert len(tree.children) == 1
