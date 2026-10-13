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
* Block location delegates to ``squall.exec_sql_scan`` (fixed-keyword
  scanning of ``EXEC SQL`` / ``END-EXEC`` delimiters over parsed
  ``squall.fixed_format.FixedLine`` code areas), exactly mirroring the
  approach in ``squall.parser.parse``.
* SQL content is classified by delegating to ``parse_exec_sql``, never by
  writing a regex that inspects SQL internals.
* Rewriting goes through ``squall.fixed_format.replace_span``/``with_code``,
  which write only columns 8-72 — the sequence area and the identification
  field (columns 73-80) are never disturbed, however much shorter or longer
  the replacement text is.
* Each line's original terminator (``\\n``, ``\\r\\n``, ``\\r``, or none on a
  final unterminated line) is captured before parsing and reattached
  verbatim after rendering — the rewrite never normalises line endings.
* A line untouched by any rewrite is emitted from the *original* source text,
  not round-tripped through ``parse_line``/``render`` — ``render`` rstrips a
  line with no identification area (a deliberate ``fixed_format`` choice for
  a line it is actually rewriting), which must not become an incidental
  whole-file trailing-whitespace change for lines the prepass never touched.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from functools import reduce
from typing import Final

from squall.exec_sql_scan import Span, find_exec_sql_spans
from squall.fixed_format import FixedLine, parse_line, render, replace_span, with_code
from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import IncludeName, Kind

# Captures the separator so a split keeps every line's original terminator —
# "\r\n", "\r", or "\n" — instead of discarding it.
_LINE_SPLIT: Final = re.compile(r"(\r\n|\r|\n)")

# ── Result type ───────────────────────────────────────────────────────────────


def _rewrite_block(indent: str, include_name: str) -> str:
    """Return the COPY statement that replaces an INCLUDE block."""
    return f"{indent}COPY {include_name}."


def _split_source(source: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split *source* into (bodies, terminators), one pair per line.

    Each terminator is exactly what followed that line in *source* — "\\r\\n",
    "\\r", "\\n", or "" for a final unterminated line — so it can be
    reattached verbatim after rendering, whether or not the line itself was
    ever touched by a rewrite.
    """
    parts = tuple(_LINE_SPLIT.split(source))
    return parts[0::2], (*parts[1::2], "")


def _join_source(bodies: Sequence[str], terminators: Sequence[str]) -> str:
    """Reassemble ``_split_source``'s output back into one string."""
    return "".join(body + term for body, term in zip(bodies, terminators, strict=True))


def _apply_rewrite(
    lines: tuple[FixedLine, ...], span: Span, code: str
) -> tuple[FixedLine, ...]:
    """Rewrite *span* to *code* via ``replace_span``, keeping any code-area
    text the scan found trailing ``END-EXEC`` on the span's last line — a
    second statement, or plain COBOL, sharing that physical line — instead
    of silently discarding it.
    """
    if span.start == span.end:
        return replace_span(lines, span.start, span.end, code + span.trailing)
    rewritten = replace_span(lines, span.start, span.end, code)
    if not span.trailing:
        return rewritten
    return (
        *rewritten[: span.end],
        with_code(rewritten[span.end], span.trailing),
        *rewritten[span.end + 1 :],
    )


def _includes(spans: Sequence[Span]) -> Iterator[tuple[Span, str]]:
    """Yield ``(span, include_name)`` for each INCLUDE span."""
    parsed_spans = ((span, parse_exec_sql(span.parse_text)) for span in spans)
    return (
        (span, parsed.include.name)
        for span, parsed in parsed_spans
        if parsed.kind is Kind.INCLUDE and isinstance(parsed.include, IncludeName)
    )


def apply_sql_prepass(source: str) -> str:
    """Rewrite ``EXEC SQL INCLUDE <name> END-EXEC`` → ``COPY <name>.``.

    All other EXEC SQL blocks and all ordinary COBOL text are returned
    byte-for-byte unchanged, including line endings — a line the rewrite
    never touches is emitted from the original source text, not rebuilt via
    ``render``.

    Every rewrite goes through ``squall.fixed_format.replace_span`` /
    ``with_code``, which write only the code area (columns 8-72) — the
    sequence area and identification field never move, however much shorter
    the replacement text is.
    """
    bodies, terminators = _split_source(source)
    lines = tuple(parse_line(body) for body in bodies)
    includes = list(_includes(find_exec_sql_spans(lines)))
    if not includes:
        return source

    rewritten_lines = reduce(
        lambda ls, item: _apply_rewrite(
            ls, item[0], _rewrite_block(item[0].indent, item[1].upper())
        ),
        includes,
        lines,
    )
    touched = frozenset(
        index
        for span, _include_name in includes
        for index in range(span.start, span.end + 1)
    )
    rewritten_bodies = tuple(
        render(rewritten_lines[index]) if index in touched else body
        for index, body in enumerate(bodies)
    )
    rewritten_source = _join_source(rewritten_bodies, terminators)
    return rewritten_source
