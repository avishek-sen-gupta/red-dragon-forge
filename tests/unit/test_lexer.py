"""
tests/unit/test_lexer.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for host-variable surfacing and lexer safety (strings, comments).
"""

from __future__ import annotations

from squall.parser._grammar import parse


def _parse_host_var_tok(tok_value: str) -> list[str]:
    """Split a HOST_VAR_TOK value like ':FOO' or ':FOO:IND' into names."""
    # tok_value always starts with ':'; segments separated by ':'
    return [s for s in tok_value.split(":") if s]


def hostvars(text: str) -> list[str]:
    """Parse *text* and return the list of primary host-var NAMEs in tree order.

    Each ``host_var`` node wraps a HOST_VAR_TOK terminal whose value looks like
    ``:FOO`` or ``:FOO:IND``.  We return only the primary (first) name per
    host_var so indicator variables don't inflate the count unexpectedly.
    """
    tree = parse(text)
    names: list[str] = []
    for node in tree.find_data("host_var"):
        for tok in node.children:
            if hasattr(tok, "type") and tok.type == "HOST_VAR_TOK":
                parts = _parse_host_var_tok(tok.value)
                if parts:
                    names.append(parts[0])
                break
    return names


# ── String-colon safety ───────────────────────────────────────────────────────


def test_string_colon_not_surfaced() -> None:
    """Colon inside a string literal must NOT become a host_var."""
    hvs = hostvars(
        "SELECT a INTO :OUT FROM t WHERE x = 'has :colon inside' AND y = :IN"
    )
    assert "OUT" in hvs
    assert "IN" in hvs
    assert len(hvs) == 2


# ── Comment-colon safety ──────────────────────────────────────────────────────


def test_line_comment_colon_not_surfaced() -> None:
    """Colon inside a line comment (--) must NOT become a host_var."""
    hvs = hostvars("SELECT a INTO :OUT FROM t -- :c is in comment")
    assert hvs == ["OUT"]


def test_block_comment_colon_not_surfaced() -> None:
    """Colon inside a block comment (/* … */) must NOT become a host_var."""
    hvs = hostvars("SELECT a INTO :OUT FROM t /* :c is in comment */")
    assert hvs == ["OUT"]


# ── Hyphenated names ──────────────────────────────────────────────────────────


def test_hyphenated_host_var() -> None:
    """COBOL-style hyphenated host-variable names must be kept intact."""
    hvs = hostvars("SELECT a INTO :HV-ACCOUNT-ID FROM t WHERE x = 1")
    assert hvs == ["HV-ACCOUNT-ID"]


# ── Indicator variables ───────────────────────────────────────────────────────


def test_indicator_var() -> None:
    """A host_var with an indicator (``:V:IND``) must surface both NAMEs.

    HOST_VAR_TOK captures the whole ``:V:IND`` atomically; we split on ``:``
    to recover the primary name and indicator name.
    """
    tree = parse("INSERT INTO t VALUES (:V:IND)")
    hv_nodes = list(tree.find_data("host_var"))
    assert len(hv_nodes) == 1
    tok = next(t for t in hv_nodes[0].children if hasattr(t, "type") and t.type == "HOST_VAR_TOK")
    names = _parse_host_var_tok(tok.value)
    assert names == ["V", "IND"]
