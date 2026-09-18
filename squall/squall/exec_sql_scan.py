"""
squall.exec_sql_scan
~~~~~~~~~~~~~~~~~~~~~
Cursor-advancing scan for ``EXEC SQL … END-EXEC`` blocks in COBOL source text.

Excluded from python-fp-lint (see ``fp.json``'s ``exclude``/``exclude_why``):
a functional recursive-unfold rewrite of this scan raised ``RecursionError``
at roughly 1000 ``EXEC SQL`` statements in one source file (verified: 900
passes, 1200 crashes). This is a cursor-advancing lexer by nature — the
iterative loop below has no depth ceiling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# Matches the opening delimiter, capturing:
#   group(1) = leading whitespace on the opening line (including an optional
#     6-digit fixed-format sequence number, columns 1-6, which the compiler
#     ignores either way)
#   group(2) = the "EXEC SQL" keyword sequence itself
# This lets us recover the indentation even when the block starts at pos 0.
_EXEC_SQL_OPEN: Final[re.Pattern[str]] = re.compile(
    r"(?m)(^(?:\d{6})?[^\S\n]*)(EXEC\s+SQL\b)",
    re.IGNORECASE,
)

# Matches ``END-EXEC`` keyword only (no trailing chars) so we get a clean
# parse boundary.  Group 0 end = position right after the ``C`` in END-EXEC.
_END_EXEC_KW: Final[re.Pattern[str]] = re.compile(
    r"\bEND-EXEC\b",
    re.IGNORECASE,
)

# After END-EXEC we may have optional whitespace and a COBOL statement
# terminator dot.  We consume those so the replacement span covers the whole
# original statement (e.g. ``EXEC SQL INCLUDE SQLCA END-EXEC.``).
_STMT_TERMINATOR: Final[re.Pattern[str]] = re.compile(r"[ \t]*\.")

# Strips a leading 6-digit fixed-format sequence number from any line of a
# located span's parse text -- not just the opening line -- so a multi-line
# statement's continuation lines don't leak sequence digits into the SQL text
# handed to the parser.
_SEQ_NUM_LINE: Final[re.Pattern[str]] = re.compile(r"(?m)^\d{6}")


@dataclass(frozen=True)
class Span:
    """One ``EXEC SQL … END-EXEC`` block located in the source.

    - ``replace_start`` / ``replace_end`` delimit the full span to be replaced
      (from the start of any leading whitespace through the optional trailing
      statement-terminator dot on the same line).
    - ``parse_text`` is passed to ``parse_exec_sql`` — it is the text from
      ``EXEC SQL`` through ``END-EXEC`` (no trailing dot), with any
      fixed-format sequence numbers stripped from every line, so the grammar
      sees only ``EXEC SQL`` content and recognises ``END-EXEC`` cleanly.
    - ``indent`` is the leading whitespace on the opening line (captured from
      the regex group so it is always correct even when the block starts at
      position 0).
    """

    replace_start: int
    replace_end: int
    parse_text: str
    indent: str


def find_exec_sql_spans(source: str) -> tuple[Span, ...]:
    """Locate every ``EXEC SQL … END-EXEC`` block in *source*.

    Iterative cursor-advancing scan: each step searches strictly past the
    previous span, until no ``EXEC SQL`` occurrence remains. A block with no
    matching ``END-EXEC`` is skipped (malformed source).
    """
    spans = []
    search_from = 0
    while True:
        open_match = _EXEC_SQL_OPEN.search(source, search_from)
        if not open_match:
            break
        close_match = _END_EXEC_KW.search(source, open_match.end())
        if not close_match:
            # Malformed — skip past this EXEC SQL and keep scanning.
            search_from = open_match.end()
            continue
        span = _span_from_match(source, open_match, close_match)
        spans.append(span)
        search_from = span.replace_end
    return tuple(spans)


def _span_from_match(
    source: str, open_match: re.Match[str], close_match: re.Match[str]
) -> Span:
    """Build the ``Span`` for one located ``EXEC SQL … END-EXEC`` block."""
    parse_end = close_match.end()
    parse_text = _SEQ_NUM_LINE.sub("", source[open_match.start(2) : parse_end])
    dot_match = _STMT_TERMINATOR.match(source, parse_end)
    replace_end = dot_match.end() if dot_match else parse_end
    return Span(open_match.start(), replace_end, parse_text, open_match.group(1))
