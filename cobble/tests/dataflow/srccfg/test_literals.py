"""Tests for the shared literal recognition vocabulary."""

from __future__ import annotations

from cobble.dataflow.srccfg.literals import is_literal


def test_empty_string_is_literal() -> None:
    """F-new-3: Empty string is treated as a literal, not a field name."""
    assert is_literal("")


def test_quoted_literals() -> None:
    assert is_literal("'ABC'")
    assert is_literal('"XYZ"')


def test_numeric_literals() -> None:
    assert is_literal("123")
    assert is_literal("-456")
    assert is_literal("+789")
    assert is_literal("12.34")


def test_figurative_constants() -> None:
    assert is_literal("SPACES")
    assert is_literal("SPACE")
    assert is_literal("LOW-VALUES")
    assert is_literal("LOW-VALUE")
    assert is_literal("HIGH-VALUES")
    assert is_literal("HIGH-VALUE")
    assert is_literal("ZERO")
    assert is_literal("ZEROS")
    assert is_literal("ZEROES")
    assert is_literal("NULL")
    assert is_literal("NULLS")
    assert is_literal("QUOTE")
    assert is_literal("QUOTES")


def test_prefixed_literals() -> None:
    assert is_literal("ALL '-'")
    assert is_literal("X'40'")
    assert is_literal("N'...'")
    assert is_literal("Z'...'")
    assert is_literal("G'...'")
    assert is_literal("B'...'")


def test_field_names_not_literals() -> None:
    """Verify whole-token matching: lookalike field names must not be filtered."""
    assert not is_literal("ALL-ITEMS")
    assert not is_literal("ALLOCATION")
    assert not is_literal("X-FLAG")
    assert not is_literal("ZERO-BALANCE")
    assert not is_literal("LOW-LIMIT")
    assert not is_literal("QUOTE-COUNT")
    assert not is_literal("WS-FIELD")
