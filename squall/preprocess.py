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

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from types import MappingProxyType
from typing import Final

from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import IncludeName, Kind

# ── Result type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PrepassResult:
    """The prepass output: the rewritten source plus the dclgen field metadata.

    *field_meta* maps a host-var name to its dclgen descriptor, gathered from the
    ``<RECORD>.json`` sidecars of the INCLUDE'd records. It is loaded ONCE here and
    passed by reference into the SQL lowering strategy (and on to the binding
    engine) — never re-read downstream.
    """

    source: str
    field_meta: Mapping[str, dict]


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


def _load_field_meta(include_name: str, copybook_dirs: Sequence) -> dict:
    """Return ``{host_var: descriptor}`` from ``<include_name>.json``, or ``{}``.

    The dclgen sidecar lives beside the copybook ProLeap inlines. Not every
    INCLUDE'd record is dclgen-generated (the hand-written SQLCA has no sidecar),
    so an absent JSON is a legitimate "no metadata" case, not an error.
    """
    candidates = (f"{include_name}.json", f"{include_name.upper()}.json")
    paths = (Path(d) / name for d in copybook_dirs for name in candidates)
    sidecar = next((p for p in paths if p.is_file()), None)
    if sidecar is None:
        return {}
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    return {field["host_var"]: field for field in data["fields"]}


def _includes(
    spans: list[tuple[int, int, str, str]],
) -> Iterator[tuple[int, int, str, str]]:
    """Yield ``(start, end, indent, include_name)`` for each INCLUDE span."""
    for start, end, parse_text, indent in spans:
        parsed = parse_exec_sql(parse_text)
        if parsed.kind is Kind.INCLUDE and isinstance(parsed.include, IncludeName):
            yield start, end, indent, parsed.include.name


def apply_sql_prepass(source: str, copybook_dirs: Sequence) -> PrepassResult:
    """Rewrite ``EXEC SQL INCLUDE <name> END-EXEC`` → ``COPY <name>.`` and load the
    dclgen JSON sidecars of the INCLUDE'd records in the same pass.

    All other EXEC SQL blocks and all ordinary COBOL text are returned
    byte-for-byte unchanged. *copybook_dirs* are searched for ``<NAME>.json``
    sidecars beside the copybooks ProLeap inlines; the gathered host-var metadata
    is returned in ``PrepassResult.field_meta`` (empty when none are present).
    """
    includes = list(_includes(_find_exec_sql_spans(source)))
    field_meta = MappingProxyType(
        {
            host_var: descriptor
            for _start, _end, _indent, include_name in includes
            for host_var, descriptor in _load_field_meta(
                include_name, copybook_dirs
            ).items()
        }
    )
    if not includes:
        return PrepassResult(source=source, field_meta=field_meta)

    # Apply replacements right-to-left (descending start) so earlier offsets stay
    # valid; reduce folds them over the source without a reassigned accumulator.
    replacements = sorted(
        (
            (start, end, _rewrite_block(indent, include_name.upper()))
            for start, end, indent, include_name in includes
        ),
        key=lambda r: r[0],
        reverse=True,
    )
    rewritten = reduce(
        lambda text, repl: text[: repl[0]] + repl[2] + text[repl[1] :],
        replacements,
        source,
    )
    return PrepassResult(source=rewritten, field_meta=field_meta)
