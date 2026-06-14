"""
squall.preprocess
~~~~~~~~~~~~~~~~~
Source-text pre-pass for COBOL programs containing EXEC SQL statements.

Runs *before* ProLeap parses the COBOL source so the parser sees only
standard COBOL.  Currently rewrites::

    EXEC SQL INCLUDE <name> END-EXEC.  →  COPY <name>.

at the same Area-A/B indentation as the original block.

Design
------
* Pure function — no global mutable state.
* Block location uses fixed-keyword scanning only (``EXEC SQL`` / ``END-EXEC``
  delimiters), exactly mirroring the approach in ``squall.parser.parse``.
* SQL content is classified by delegating to ``parse_exec_sql``, never by
  writing a regex that inspects SQL internals.
"""

from __future__ import annotations

import re
from typing import Final

from squall.parser.parse import parse_exec_sql

# ── Fixed-delimiter scanner ───────────────────────────────────────────────────

# Matches the opening delimiter, capturing:
#   group(1) = leading whitespace on the opening line
#   group(2) = the "EXEC SQL" keyword sequence itself
# This lets us recover the indentation even when the block starts at pos 0.
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


def _find_exec_sql_spans(
    source: str,
) -> list[tuple[int, int, str, str]]:
    """Locate every ``EXEC SQL … END-EXEC`` block in *source*.

    Returns a list of ``(replace_start, replace_end, parse_text, indent)``
    tuples where:

    - ``replace_start`` / ``replace_end`` delimit the full span to be replaced
      (from the start of any leading whitespace through the optional trailing
      statement-terminator dot on the same line).
    - ``parse_text`` is passed to ``parse_exec_sql`` — it is the text from
      ``EXEC SQL`` through ``END-EXEC`` (no trailing dot) so the grammar
      recognises ``END-EXEC`` cleanly.
    - ``indent`` is the leading whitespace on the opening line (captured from
      the regex group so it is always correct even when the block starts at
      position 0).

    If a block has no matching ``END-EXEC`` it is skipped (malformed source).
    """
    results: list[tuple[int, int, str, str]] = []
    search_from = 0
    while True:
        open_match = _EXEC_SQL_OPEN.search(source, search_from)
        if open_match is None:
            break
        # group(1) is the leading whitespace; the EXEC keyword starts at
        # open_match.start(2) [i.e. end of group(1)].
        indent = open_match.group(1)
        # replace_start covers the leading whitespace too.
        replace_start = open_match.start()
        # parse_text starts at EXEC (no leading whitespace).
        exec_start = open_match.start(2)
        close_match = _END_EXEC_KW.search(source, open_match.end())
        if close_match is None:
            # Malformed — skip.
            search_from = open_match.end()
            continue
        parse_end = close_match.end()
        parse_text = source[exec_start:parse_end]
        # replace_end extends over an optional trailing ``  .`` on the same line.
        dot_match = _STMT_TERMINATOR.match(source, parse_end)
        replace_end = dot_match.end() if dot_match is not None else parse_end
        results.append((replace_start, replace_end, parse_text, indent))
        search_from = replace_end
    return results


def _rewrite_block(indent: str, include_name: str) -> str:
    """Return the COPY statement that replaces an INCLUDE block."""
    return f"{indent}COPY {include_name}."


def apply_sql_prepass(source: str) -> str:
    """Rewrite ``EXEC SQL INCLUDE <name> END-EXEC`` → ``COPY <name>.``

    All other EXEC SQL blocks and all ordinary COBOL text are returned
    byte-for-byte unchanged.

    Parameters
    ----------
    source:
        Raw COBOL source text (may contain multiple EXEC SQL blocks).

    Returns
    -------
    str
        Source with every INCLUDE block replaced by the equivalent COPY
        statement, at the same indentation as the original block.
    """
    spans = _find_exec_sql_spans(source)
    if not spans:
        return source

    # Apply replacements right-to-left so earlier offsets stay valid.
    replacements: list[tuple[int, int, str]] = []
    for replace_start, replace_end, parse_text, indent in spans:
        parsed = parse_exec_sql(parse_text)
        if parsed.kind == "include" and parsed.include_name is not None:
            # COPY target is always uppercased regardless of source case.
            replacement = _rewrite_block(indent, parsed.include_name.upper())
            replacements.append((replace_start, replace_end, replacement))

    if not replacements:
        return source

    replacements.sort(key=lambda r: r[0], reverse=True)
    result = source
    for start, end, sub in replacements:
        result = result[:start] + sub + result[end:]
    return result
