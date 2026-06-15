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
from functools import reduce
from importlib.resources import files
from itertools import pairwise
from typing import Final

from lark import Lark, Token, Tree

# ── Frozen types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HostVar:
    name: str  # e.g. "WS-BAL" (no leading colon)
    indicator: str | None  # e.g. "WS-IND" for :WS-BAL:WS-IND, else None


@dataclass(frozen=True)
class ParsedSql:
    kind: str  # the grammar kind, e.g. "select_into"
    in_vars: tuple[HostVar, ...]  # input (bind) host vars, in source order
    out_vars: tuple[HostVar, ...]  # output (INTO) host vars, in order
    cursor: str | None  # cursor name for cursor statements, else None
    query: str  # cleaned SQL for the DB
    include_name: str | None = None  # INCLUDE target name, e.g. "SQLCA", else None
    # Connection management (kinds connect / set_connection / disconnect).
    connect_variant: str | None = None  # "TO" / "RESET" (connect only); None otherwise
    connect_db: str | HostVar | None = None  # target db: literal (upper) or HostVar
    # WHENEVER directive (kind == "whenever"); None for every other kind.
    whenever_condition: str | None = None  # "SQLERROR" / "NOT FOUND" / "SQLWARNING"
    whenever_action: str | None = None  # "CONTINUE" / "GOTO"
    whenever_target: str | None = None  # GO TO label, else None


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
_EXEC_SQL_RE: Final[re.Pattern[str]] = re.compile(r"^\s*EXEC\s+SQL\s+", re.IGNORECASE)
_END_EXEC_RE: Final[re.Pattern[str]] = re.compile(r"\s*END-EXEC\s*$", re.IGNORECASE)

# ── Cursor statement kinds ────────────────────────────────────────────────────

_CURSOR_KINDS: Final[frozenset[str]] = frozenset(
    {"declare_cursor", "open_", "close", "fetch"}
)

# Kinds where query == "" (no SQL sent to the DB engine)
_NO_QUERY_KINDS: Final[frozenset[str]] = frozenset({"fetch", "open_", "close"})

# Kinds with an INTO clause to strip from the query
_HAS_INTO_CLAUSE: Final[frozenset[str]] = frozenset({"select_into", "values_into"})


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_envelope(text: str) -> str:
    """Strip 'EXEC SQL' prefix and 'END-EXEC' suffix from *text*."""
    return _END_EXEC_RE.sub("", _EXEC_SQL_RE.sub("", text)).strip()


def _parse_host_var_tok(tok_value: str) -> HostVar:
    """Convert a HOST_VAR_TOK string like ':FOO' or ':FOO:IND' to HostVar."""
    # tok_value always starts with ':'; split on ':' and discard empty strings
    parts = [s for s in tok_value.split(":") if s]
    name = parts[0]
    indicator = parts[1] if len(parts) >= 2 else None
    return HostVar(name=name, indicator=indicator)


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


def _include_name(stmt: Tree, kind: str) -> str | None:
    """Return the NAME token for an ``include`` statement, else None."""
    if kind != "include":
        return None
    for child in stmt.children:
        if isinstance(child, Token) and child.type == "NAME":
            return str(child)
    return None


def _conn_target(stmt: Tree) -> str | HostVar | None:
    """The connect target db: a NAME literal (upper-cased) or a HostVar, else None.

    Reads the structured ``conn_target`` production (``NAME | host_var``).
    """
    node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "conn_target"),
        None,
    )
    if node is None:
        return None
    inner = node.children[0]
    if isinstance(inner, Token) and inner.type == "NAME":
        return str(inner).upper()
    # host_var Tree -> its single HOST_VAR_TOK child.
    return _parse_host_var_tok(inner.children[0].value)


def _connection_fields(
    stmt: Tree, kind: str
) -> tuple[str | None, str | HostVar | None]:
    """Return (variant, target) for connection statements, else (None, None).

    ``connect`` reads the structured grammar (RESET terminal vs conn_target).
    ``set_connection`` / ``disconnect`` take their first NAME token; their
    leading keywords are genuine terminals, so this is a structural read, not
    keyword value-matching.
    """
    if kind == "connect":
        if any(isinstance(c, Token) and c.type == "RESET" for c in stmt.children):
            return "RESET", None
        return "TO", _conn_target(stmt)
    if kind in ("set_connection", "disconnect"):
        name = next(
            (
                str(c)
                for c in stmt.children
                if isinstance(c, Token) and c.type == "NAME"
            ),
            None,
        )
        return None, (name.upper() if name is not None else None)
    return None, None


def _whenever_fields(
    stmt: Tree, kind: str
) -> tuple[str | None, str | None, str | None]:
    """Return (condition, action, target) for a WHENEVER directive, else Nones."""
    if kind != "whenever":
        return None, None, None
    cond_node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "whenever_cond"),
        None,
    )
    action_node = next(
        (
            c
            for c in stmt.children
            if isinstance(c, Tree) and c.data == "whenever_action"
        ),
        None,
    )
    condition = _whenever_condition(cond_node) if cond_node is not None else None
    action, target = (
        _whenever_action(action_node) if action_node is not None else (None, None)
    )
    return condition, action, target


def _whenever_condition(node: Tree) -> str:
    """Normalise the condition tokens to 'SQLERROR' / 'NOT FOUND' / 'SQLWARNING'."""
    tokens = [str(c) for c in node.children if isinstance(c, Token)]
    return " ".join(tokens).upper()


def _whenever_action(node: Tree) -> tuple[str, str | None]:
    """Return ('CONTINUE', None) or ('GOTO', <target>) for the action subtree."""
    tokens = [c for c in node.children if isinstance(c, Token)]
    if tokens and str(tokens[0]).upper() == "CONTINUE":
        return "CONTINUE", None
    # GOTO <name> or GO TO <name>: the target is the trailing NAME token.
    target = str(tokens[-1]) if tokens else None
    return "GOTO", target


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
    return next(
        (
            prev
            for prev, cur in pairwise(stmt.children)
            if isinstance(cur, Tree)
            and cur.data == "into_list"
            and isinstance(prev, Token)
            and prev.type == "INTO"
        ),
        None,
    )


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

    # For DECLARE <name> CURSOR FOR <select>, the executable query is just the
    # SELECT (the FOR clause) — OPEN runs that. Locate the FOR token from the
    # parse tree (structure, not a string split) and start the query after it.
    # No host vars precede FOR, so slicing the rewritten result is safe.
    for_tok = _find_for_token(stmt) if kind == "declare_cursor" else None
    query_start = for_tok.end_pos if for_tok is not None else 0

    # --- gather replacements: list of (start, end, replacement) ---------------
    replacements: list[tuple[int, int, str]] = []

    # input host_var tokens -> "?"
    for tok in _collect_input_hv_tokens(stmt):
        replacements.append((tok.start_pos, tok.end_pos, "?"))

    # INTO clause removal for select_into / values_into. Consume one leading
    # space so removing "col INTO :a FROM" yields "col FROM" (single space)
    # WITHOUT a body-wide whitespace regex (which would mangle string literals).
    if kind in _HAS_INTO_CLAUSE:
        into_tok = _find_into_keyword_token(stmt)
        into_list_node = _find_into_list_node(stmt)
        if into_tok is not None and into_list_node is not None:
            raw = into_tok.start_pos
            # Consume one leading space if present (safe at pos 0: the slice is "").
            start = raw - (1 if inner[raw - 1 : raw] == " " else 0)
            replacements.append((start, into_list_node.meta.end_pos, ""))

    if not replacements:
        return inner[query_start:].strip()

    # Apply right-to-left (descending start) so offsets don't drift; reduce folds
    # the edits over *inner* without a reassigned accumulator.
    ordered = sorted(replacements, key=lambda r: r[0], reverse=True)
    result = reduce(
        lambda acc, repl: acc[: repl[0]] + repl[2] + acc[repl[1] :], ordered, inner
    )
    return result[query_start:].strip()


def _find_for_token(stmt: Tree) -> Token | None:
    """Return the first FOR keyword token (DECLARE … CURSOR **FOR** …), or None.

    The first FOR is the cursor declaration's; any later FOR (e.g. a trailing
    ``FOR READ ONLY`` inside the SELECT) belongs to the query and is left alone.
    """
    for child in stmt.children:
        if isinstance(child, Token) and child.type == "FOR":
            return child
    return None


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
    inc_name = _include_name(stmt, kind)
    conn_variant, conn_db = _connection_fields(stmt, kind)
    wh_cond, wh_action, wh_target = _whenever_fields(stmt, kind)

    return ParsedSql(
        kind=kind,
        in_vars=in_vars,
        out_vars=out_vars,
        cursor=cursor,
        query=query,
        include_name=inc_name,
        connect_variant=conn_variant,
        connect_db=conn_db,
        whenever_condition=wh_cond,
        whenever_action=wh_action,
        whenever_target=wh_target,
    )
