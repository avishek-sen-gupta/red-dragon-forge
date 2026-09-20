"""
squall.exec_sql_scan
~~~~~~~~~~~~~~~~~~~~~
Cursor-advancing scan for ``EXEC SQL … END-EXEC`` blocks over fixed-format
COBOL source, matched against code areas only.

Excluded from python-fp-lint (see ``fp.json``'s ``exclude``/``exclude_why``):
a functional recursive-unfold rewrite of this scan raised ``RecursionError``
at roughly 1000 ``EXEC SQL`` statements in one source file (verified: 900
passes, 1200 crashes). This is a cursor-advancing lexer by nature — the
iterative loop below has no depth ceiling. ``_line_starts`` does not share
that justification (it is a plain prefix sum) and is written functionally
below so it does not lean on the exclusion either.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate
from typing import Final

from squall.fixed_format import FixedLine

# Matches the opening delimiter within the joined code-area text, capturing:
#   group(1) = leading whitespace on the opening code area's line
#   group(2) = the "EXEC SQL" keyword sequence itself
# Code areas never carry sequence digits (columns 1-6) by construction, so —
# unlike a scan over raw source — there is no sequence-number alternative to
# match here.
_EXEC_SQL_OPEN: Final[re.Pattern[str]] = re.compile(
    r"(?m)(^[^\S\n]*)(EXEC\s+SQL\b)",
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


@dataclass(frozen=True)
class Span:
    """One ``EXEC SQL … END-EXEC`` block located across one or more lines.

    - ``start`` / ``end`` are the inclusive line indices — into the same
      ``FixedLine`` sequence passed to ``find_exec_sql_spans`` — spanning the
      whole statement, ready to hand straight to
      ``squall.fixed_format.replace_span``.
    - ``parse_text`` is passed to ``parse_exec_sql`` — the code-area text
      from ``EXEC SQL`` through ``END-EXEC`` (no trailing dot), with each
      line's code area joined by ``\\n``. It contains no sequence digits by
      construction: it is drawn only from the code area (columns 8-72),
      never from columns 1-7 or 73-80.
    - ``indent`` is the leading whitespace within the code area of the
      opening line — what a rewrite passes on to ``with_code`` /
      ``replace_span`` to keep the replacement at the same Area A/B column.
    - ``trailing`` is whatever code-area text follows the statement (past
      ``END-EXEC`` and its optional terminating dot) on the span's *last*
      line — a second statement or plain COBOL sharing that physical line.
      A rewrite must fold this back in rather than discard it: it is empty
      in the overwhelmingly common case of one statement per line.
    """

    start: int
    end: int
    parse_text: str
    indent: str
    trailing: str


def find_exec_sql_spans(lines: Sequence[FixedLine]) -> tuple[Span, ...]:
    """Locate every ``EXEC SQL … END-EXEC`` block across *lines*' code areas.

    The code areas are joined with ``\\n`` into one search text so a
    multi-line statement is found in a single pass; matched offsets are
    mapped back to line indices so the result addresses ``lines`` directly.
    Iterative cursor-advancing scan: each step searches strictly past the
    previous span, until no ``EXEC SQL`` occurrence remains. A block with no
    matching ``END-EXEC`` is skipped (malformed source).
    """
    code_texts = tuple(line.code for line in lines)
    joined = "\n".join(code_texts)
    line_starts = _line_starts(code_texts)

    spans = []
    search_from = 0
    while True:
        open_match = _EXEC_SQL_OPEN.search(joined, search_from)
        if not open_match:
            break
        close_match = _END_EXEC_KW.search(joined, open_match.end())
        if not close_match:
            # Malformed — skip past this EXEC SQL and keep scanning.
            search_from = open_match.end()
            continue
        span, resume_from = _span_from_match(
            joined, open_match, close_match, line_starts, code_texts
        )
        spans.append(span)
        search_from = resume_from
    return tuple(spans)


def _line_starts(code_texts: Sequence[str]) -> tuple[int, ...]:
    """Return the joined-text offset at which each code area's text starts.

    A plain prefix sum over each code area's length (plus one for the ``\\n``
    joiner) — expressed with ``itertools.accumulate`` rather than an
    append-in-a-loop, since this needs none of the recursion-depth latitude
    the module's ``fp.json`` exclusion exists for.
    """
    if not code_texts:
        return ()
    ends = tuple(accumulate(len(text) + 1 for text in code_texts))
    return (0,) + ends[:-1]


def _line_at(offset: int, line_starts: Sequence[int]) -> int:
    """Return the index of the line whose code area contains *offset*."""
    return bisect_right(line_starts, offset) - 1


def _span_from_match(
    joined: str,
    open_match: re.Match[str],
    close_match: re.Match[str],
    line_starts: Sequence[int],
    code_texts: Sequence[str],
) -> tuple[Span, int]:
    """Build the ``Span`` for one located block, and where to resume scanning."""
    parse_end = close_match.end()
    dot_match = _STMT_TERMINATOR.match(joined, parse_end)
    resume_from = dot_match.end() if dot_match else parse_end
    start_line = _line_at(open_match.start(1), line_starts)
    end_line = _line_at(parse_end - 1, line_starts)
    parse_text = joined[open_match.start(2) : parse_end]
    end_line_code_end = line_starts[end_line] + len(code_texts[end_line])
    trailing = joined[resume_from:end_line_code_end]
    span = Span(start_line, end_line, parse_text, open_match.group(1), trailing)
    return span, resume_from
