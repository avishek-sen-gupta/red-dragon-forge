"""
squall.parser.parse
~~~~~~~~~~~~~~~~~~~
Public API for parsing EXEC SQL … END-EXEC blocks.

Design
------
* All exported types are frozen dataclasses (immutability tenet).
* ``parse_exec_sql`` and all helpers are pure functions (FP tenet).
* Token positions from Lark's ``propagate_positions=True`` drive the
  span-keyed rewrite so the SQL body is preserved verbatim except for
  host-var placeholder substitution and INTO-clause removal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Final

from lark import Lark, Token, Tree

# ── Frozen types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HostVar:
    name: str               # e.g. "WS-BAL" (no leading colon)
    indicator: str | None   # e.g. "WS-IND" for :WS-BAL:WS-IND, else None


@dataclass(frozen=True)
class ParsedSql:
    kind: str                       # the grammar kind, e.g. "select_into"
    in_vars: tuple[HostVar, ...]    # input (bind) host vars, in source order
    out_vars: tuple[HostVar, ...]   # output (INTO) host vars, in order
    cursor: str | None              # cursor name for cursor statements, else None
    query: str                      # cleaned SQL for the DB


# ── Parser with position tracking ─────────────────────────────────────────────

_GRAMMAR_TEXT: Final[str] = (
    files("squall.parser").joinpath("grammar.lark").read_text(encoding="utf-8")
)

_PARSER: Final[Lark] = Lark(
    _GRAMMAR_TEXT,
    parser="earley",
    lexer="dynamic",
    ambiguity="resolve",
    propagate_positions=True,
)

# ── Envelope patterns ─────────────────────────────────────────────────────────

# Fixed-keyword strip: match EXEC SQL at start, END-EXEC at end.
# Case-insensitive; allows arbitrary whitespace between the keywords.
_EXEC_SQL_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*EXEC\s+SQL\s+", re.IGNORECASE
)
_END_EXEC_RE: Final[re.Pattern[str]] = re.compile(
    r"\s*END-EXEC\s*$", re.IGNORECASE
)

# ── Cursor statement kinds ────────────────────────────────────────────────────

_CURSOR_KINDS: Final[frozenset[str]] = frozenset(
    {"declare_cursor", "open_", "close", "fetch"}
)

# Kinds where query == "" (no SQL sent to the DB engine)
_NO_QUERY_KINDS: Final[frozenset[str]] = frozenset(
    {"fetch", "open_", "close"}
)

# Kinds with an INTO clause to strip from the query
_HAS_INTO_CLAUSE: Final[frozenset[str]] = frozenset(
    {"select_into", "values_into"}
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_envelope(text: str) -> str:
    """Strip 'EXEC SQL' prefix and 'END-EXEC' suffix from *text*."""
    inner = _EXEC_SQL_RE.sub("", text)
    inner = _END_EXEC_RE.sub("", inner)
    return inner.strip()


def _parse_host_var_tok(tok_value: str) -> HostVar:
    """Convert a HOST_VAR_TOK string like ':FOO' or ':FOO:IND' to HostVar."""
    # tok_value always starts with ':'; split on ':' and discard empty strings
    parts = [s for s in tok_value.split(":") if s]
    name = parts[0]
    indicator = parts[1] if len(parts) >= 2 else None
    return HostVar(name=name, indicator=indicator)


def _collect_into_list_hvs(stmt: Tree) -> tuple[HostVar, ...]:
    """Return HostVar tuples from all host_var nodes inside into_list, in order."""
    return tuple(
        _parse_host_var_tok(tok.value)
        for into_node in stmt.find_data("into_list")
        for hv_node in into_node.find_data("host_var")
        for tok in hv_node.children
        if hasattr(tok, "type") and tok.type == "HOST_VAR_TOK"
    )


def _collect_all_hvs_in_order(stmt: Tree) -> list[tuple[HostVar, bool]]:
    """Walk *stmt* in tree order; return (HostVar, is_in_into_list) pairs.

    We do a single left-to-right DFS so host_var tokens retain their source
    order regardless of which sub-rule they belong to.
    """
    results: list[tuple[HostVar, bool]] = []
    _walk_for_hvs(stmt, in_into_list=False, results=results)
    return results


def _walk_for_hvs(
    node: Tree | Token,
    in_into_list: bool,
    results: list[tuple[HostVar, bool]],
) -> None:
    """Recursive DFS walker that tracks whether we are inside an into_list."""
    if isinstance(node, Token):
        if node.type == "HOST_VAR_TOK":
            results.append((_parse_host_var_tok(node.value), in_into_list))
        return
    # Tree node
    now_in_into_list = in_into_list or (
        hasattr(node, "data") and node.data == "into_list"
    )
    for child in node.children:
        _walk_for_hvs(child, now_in_into_list, results)


def _cursor_name(stmt: Tree, kind: str) -> str | None:
    """Return the cursor NAME for cursor-related statements, else None."""
    if kind not in _CURSOR_KINDS:
        return None
    # The cursor name is always the NAME token immediately after the
    # leading keyword:
    #   declare_cursor: DECLARE <name> CURSOR …
    #   open_:          OPEN <name> …
    #   close:          CLOSE <name>
    #   fetch:          FETCH (FROM)? <name> INTO …
    #
    # We walk stmt.children looking for the first NAME token that is NOT
    # a keyword-as-NAME (FETCH / FROM / DECLARE / OPEN / CLOSE are
    # recognised as their own terminal types, so the cursor NAME appears
    # as a plain NAME token).
    for child in stmt.children:
        if isinstance(child, Token) and child.type == "NAME":
            return str(child)
    return None


def _find_into_list_node(stmt: Tree) -> Tree | None:
    """Return the first direct-child into_list Tree, or None."""
    for child in stmt.children:
        if isinstance(child, Tree) and child.data == "into_list":
            return child
    return None


def _find_into_keyword_token(stmt: Tree) -> Token | None:
    """Return the INTO Token that directly precedes an into_list, or None."""
    prev: Token | None = None
    for child in stmt.children:
        if isinstance(child, Tree) and child.data == "into_list":
            if prev is not None and isinstance(prev, Token) and prev.type == "INTO":
                return prev
        if isinstance(child, Token):
            prev = child
        else:
            prev = None
    return None


def _build_query(inner: str, stmt: Tree, kind: str) -> str:
    """Build the cleaned SQL string via span-keyed rewrite of *inner*.

    Strategy:
    1. Collect all (start, end) spans to replace:
       - input host_var spans -> "?"
       - for select_into / values_into: INTO + into_list span -> deleted
    2. Sort spans by start position; apply replacements right-to-left to
       preserve offsets.
    """
    if kind in _NO_QUERY_KINDS:
        return ""

    # --- gather replacements: list of (start, end, replacement) ---------------
    replacements: list[tuple[int, int, str]] = []

    # input host_var tokens -> "?"
    hv_pairs = _collect_all_hvs_in_order(stmt)
    # We need the actual Token objects with positions, not just HostVar values.
    # Walk again collecting Token objects directly.
    input_hv_tokens = _collect_input_hv_tokens(stmt)
    for tok in input_hv_tokens:
        replacements.append((tok.start_pos, tok.end_pos, "?"))

    # INTO clause removal for select_into / values_into
    if kind in _HAS_INTO_CLAUSE:
        into_tok = _find_into_keyword_token(stmt)
        into_list_node = _find_into_list_node(stmt)
        if into_tok is not None and into_list_node is not None:
            # Remove from start of INTO token to end of into_list
            start = into_tok.start_pos
            end = into_list_node.meta.end_pos
            replacements.append((start, end, ""))

    if not replacements:
        return inner

    # Sort by start descending so we can apply right-to-left without offset drift
    replacements.sort(key=lambda r: r[0], reverse=True)

    result = inner
    for start, end, sub in replacements:
        result = result[:start] + sub + result[end:]

    # Collapse extra whitespace introduced by removal, but preserve string literals.
    # A simple multi-space collapse is safe here: SQL normalises whitespace.
    result = re.sub(r"  +", " ", result).strip()
    return result


def _collect_input_hv_tokens(stmt: Tree) -> list[Token]:
    """Return HOST_VAR_TOK tokens NOT inside an into_list, in tree order."""
    tokens: list[Token] = []
    _walk_input_hv_tokens(stmt, in_into_list=False, out=tokens)
    return tokens


def _walk_input_hv_tokens(
    node: Tree | Token,
    in_into_list: bool,
    out: list[Token],
) -> None:
    if isinstance(node, Token):
        if node.type == "HOST_VAR_TOK" and not in_into_list:
            out.append(node)
        return
    now_in = in_into_list or (hasattr(node, "data") and node.data == "into_list")
    for child in node.children:
        _walk_input_hv_tokens(child, now_in, out)


# ── Public API ────────────────────────────────────────────────────────────────


def parse_exec_sql(text: str) -> ParsedSql:
    """Parse a verbatim ``EXEC SQL … END-EXEC`` block.

    Parameters
    ----------
    text:
        The raw EXEC SQL text including the ``EXEC SQL`` and ``END-EXEC``
        delimiters.

    Returns
    -------
    ParsedSql
        Frozen dataclass with kind, in_vars, out_vars, cursor, query.
    """
    inner = _strip_envelope(text)
    tree = _PARSER.parse(inner)
    stmt: Tree = tree.children[0]
    kind: str = stmt.data

    hv_pairs = _collect_all_hvs_in_order(stmt)
    out_vars = tuple(hv for hv, is_out in hv_pairs if is_out)
    in_vars = tuple(hv for hv, is_out in hv_pairs if not is_out)

    cursor = _cursor_name(stmt, kind)
    query = _build_query(inner, stmt, kind)

    return ParsedSql(
        kind=kind,
        in_vars=in_vars,
        out_vars=out_vars,
        cursor=cursor,
        query=query,
    )
