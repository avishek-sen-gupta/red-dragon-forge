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
from functools import reduce
from importlib.resources import files
from itertools import pairwise
from typing import Final

from lark import Lark, Token, Tree

from squall.parser.sql_model import (
    ConnectReset,
    ConnectSpec,
    ConnectTo,
    Continue,
    CursorRef,
    DbName,
    GoTo,
    HostVar,
    HostVarDb,
    IncludeName,
    IncludeRef,
    Kind,
    LiteralDb,
    NamedCursor,
    NoConnect,
    NoCursor,
    NoInclude,
    NoOpAction,
    ParsedSql,
    WheneverAction,
    WheneverCondition,
)

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

_CURSOR_KINDS: Final[frozenset[Kind]] = frozenset(
    {Kind.DECLARE_CURSOR, Kind.OPEN, Kind.CLOSE, Kind.FETCH}
)

# Kinds where query == "" (no SQL sent to the DB engine)
_NO_QUERY_KINDS: Final[frozenset[Kind]] = frozenset({Kind.FETCH, Kind.OPEN, Kind.CLOSE})

# Kinds with an INTO clause to strip from the query
_HAS_INTO_CLAUSE: Final[frozenset[Kind]] = frozenset(
    {Kind.SELECT_INTO, Kind.VALUES_INTO}
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_envelope(text: str) -> str:
    """Strip 'EXEC SQL' prefix and 'END-EXEC' suffix from *text*."""
    return _END_EXEC_RE.sub("", _EXEC_SQL_RE.sub("", text)).strip()


def _parse_host_var_tok(tok_value: str) -> HostVar:
    """Convert a HOST_VAR_TOK string like ':FOO', ': FOO' or ':FOO:IND' to HostVar."""
    # tok_value always starts with ':'; split on ':', drop the whitespace either
    # colon may be followed by, and discard empty strings
    parts = [s.strip() for s in tok_value.split(":") if s.strip()]
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


def _include_ref(stmt: Tree, kind: Kind) -> IncludeRef:
    """The INCLUDE target as ``IncludeName(name)``, else NoInclude()."""
    if kind is not Kind.INCLUDE:
        return NoInclude()
    for child in stmt.children:
        if isinstance(child, Token) and child.type == "NAME":
            return IncludeName(str(child))
    return NoInclude()


def _connect_db(stmt: Tree) -> DbName:
    """The CONNECT TO target db: a NAME literal (upper-cased) or a host var.

    Reads the structured ``conn_target`` production (``NAME | host_var``).
    """
    node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "conn_target"),
        None,
    )
    if node is None:
        raise AssertionError("CONNECT TO without a conn_target")
    inner = node.children[0]
    if isinstance(inner, Token) and inner.type == "NAME":
        return LiteralDb(str(inner).upper())
    # host_var Tree -> its single HOST_VAR_TOK child.
    return HostVarDb(_parse_host_var_tok(_token(_subtree(inner).children[0]).value))


def _pos(offset: int | None) -> int:
    """A token's source offset. Lark types these Optional, but the parser is
    built with positions propagated, so an absent one is a broken Lark contract
    rather than something a COBOL member can cause."""
    if offset is None:
        raise AssertionError("Lark token carries no source position")
    return offset


def _subtree(branch: object) -> Tree:
    """A child that the grammar guarantees is a subtree rather than a token."""
    if not isinstance(branch, Tree):
        raise AssertionError(f"expected a subtree, got {type(branch).__name__}")
    return branch


def _token(branch: object) -> Token:
    """A child that the grammar guarantees is a token rather than a subtree."""
    if not isinstance(branch, Token):
        raise AssertionError(f"expected a token, got {type(branch).__name__}")
    return branch


def _connect_spec(stmt: Tree, kind: Kind) -> ConnectSpec:
    """The connection target. CONNECT RESET -> ConnectReset; CONNECT TO / SET
    CONNECTION / DISCONNECT <name> -> ConnectTo(db); else NoConnect.

    ``connect`` reads the structured grammar (RESET terminal vs conn_target).
    ``set_connection`` / ``disconnect`` take their first NAME token (literal);
    their leading keywords are genuine terminals — a structural read.
    """
    if kind is Kind.CONNECT:
        if any(isinstance(c, Token) and c.type == "RESET" for c in stmt.children):
            return ConnectReset()
        return ConnectTo(_connect_db(stmt))
    if kind in (Kind.SET_CONNECTION, Kind.DISCONNECT):
        name = next(
            (
                str(c)
                for c in stmt.children
                if isinstance(c, Token) and c.type == "NAME"
            ),
            "",
        )
        return ConnectTo(LiteralDb(name.upper()))
    return NoConnect()


def _whenever_fields(
    stmt: Tree, kind: Kind
) -> tuple[WheneverCondition, WheneverAction]:
    """Return (condition, action) for a WHENEVER directive, else (NONE, NoOpAction)."""
    if kind is not Kind.WHENEVER:
        return WheneverCondition.NONE, NoOpAction()
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
    condition = (
        _whenever_condition(cond_node)
        if cond_node is not None
        else WheneverCondition.NONE
    )
    action = _whenever_action(action_node) if action_node is not None else NoOpAction()
    return condition, action


def _whenever_condition(node: Tree) -> WheneverCondition:
    """The matching WheneverCondition member, or NONE for one Db2 does not define.

    The grammar admits a bare NAME as a condition, and the opaque-run action can
    swallow the second word of NOT FOUND, so the tokens here are not guaranteed
    to name a member. An unguarded lookup raised instead, which reached cobble's
    corpus parse as a member it could no longer parse at all.
    """
    tokens = [str(c) for c in node.children if isinstance(c, Token)]
    joined = " ".join(tokens).upper()
    return next(
        (member for member in WheneverCondition if member.value == joined),
        WheneverCondition.NONE,
    )


_GOTO_OPENERS = ("GOTO", "GO")


def _whenever_action(node: Tree) -> WheneverAction:
    """Continue(), GoTo(target), or NoOpAction for an action Db2 does not define.

    Only a GOTO/GO TO yields a target. Treating every non-CONTINUE action as one
    and taking its last token invented jumps: PERFORM/STOP/DO are Pro*COBOL, and
    `DO HANDLER()` came back as GoTo(')') -- a paragraph name a CFG would then
    draw an edge to.
    """
    tokens = [c for c in node.children if isinstance(c, Token)]
    match [str(t).upper() for t in tokens]:
        case ["CONTINUE", *_]:
            return Continue()
        case [opener, *_] if opener in _GOTO_OPENERS:
            return GoTo(str(tokens[-1]))
        case _:
            return NoOpAction()


def _cursor_ref(stmt: Tree, kind: Kind) -> CursorRef:
    """The cursor as ``NamedCursor(name)`` for cursor statements, else NoCursor().

    The cursor name is the first NAME token after the leading keyword
    (DECLARE/OPEN/CLOSE/FETCH are their own terminals, so the cursor name
    surfaces as a plain NAME):
      declare_cursor: DECLARE <name> CURSOR …   open_: OPEN <name> …
      close:          CLOSE <name>              fetch: FETCH (FROM)? <name> INTO …
    """
    if kind not in _CURSOR_KINDS:
        return NoCursor()
    for child in stmt.children:
        if isinstance(child, Token) and child.type == "NAME":
            return NamedCursor(str(child))
    return NoCursor()


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


def _build_query(inner: str, stmt: Tree, kind: Kind) -> str:
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
    for_tok = _find_for_token(stmt) if kind is Kind.DECLARE_CURSOR else None
    query_start = for_tok.end_pos if for_tok is not None else 0

    # --- gather replacements: list of (start, end, replacement) ---------------
    replacements: list[tuple[int, int, str]] = []

    # input host_var tokens -> "?"
    for tok in _collect_input_hv_tokens(stmt):
        replacements.append((_pos(tok.start_pos), _pos(tok.end_pos), "?"))

    # INTO clause removal for select_into / values_into. Consume one leading
    # space so removing "col INTO :a FROM" yields "col FROM" (single space)
    # WITHOUT a body-wide whitespace regex (which would mangle string literals).
    if kind in _HAS_INTO_CLAUSE:
        into_tok = _find_into_keyword_token(stmt)
        into_list_node = _find_into_list_node(stmt)
        if into_tok is not None and into_list_node is not None:
            raw = _pos(into_tok.start_pos)
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
    stmt = _subtree(tree.children[0])
    kind: Kind = Kind(stmt.data)

    hv_pairs = _collect_all_hvs_in_order(stmt)
    out_vars = tuple(hv for hv, is_out in hv_pairs if is_out)
    in_vars = tuple(hv for hv, is_out in hv_pairs if not is_out)

    cursor = _cursor_ref(stmt, kind)
    query = _build_query(inner, stmt, kind)
    include = _include_ref(stmt, kind)
    connect = _connect_spec(stmt, kind)
    wh_cond, wh_action = _whenever_fields(stmt, kind)

    return ParsedSql(
        kind=kind,
        in_vars=in_vars,
        out_vars=out_vars,
        cursor=cursor,
        query=query,
        include=include,
        connect=connect,
        whenever_condition=wh_cond,
        whenever_action=wh_action,
    )
