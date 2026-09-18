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
  scanning of ``EXEC SQL`` / ``END-EXEC`` delimiters), exactly mirroring the
  approach in ``squall.parser.parse``.
* SQL content is classified by delegating to ``parse_exec_sql``, never by
  writing a regex that inspects SQL internals.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from types import MappingProxyType

from squall.exec_sql_scan import Span, find_exec_sql_spans
from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import FieldMeta, IncludeName, Kind

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
    field_meta: Mapping[str, FieldMeta]


def _rewrite_block(indent: str, include_name: str) -> str:
    """Return the COPY statement that replaces an INCLUDE block."""
    return f"{indent}COPY {include_name}."


def _load_field_meta(
    include_name: str, copybook_dirs: Sequence
) -> Mapping[str, FieldMeta]:
    """Return ``{host_var: descriptor}`` from ``<include_name>.json``, or ``{}``.

    The dclgen sidecar lives beside the copybook ProLeap inlines. Not every
    INCLUDE'd record is dclgen-generated (the hand-written SQLCA has no sidecar),
    so an absent JSON is a legitimate "no metadata" case, not an error.
    """
    candidates = (f"{include_name}.json", f"{include_name.upper()}.json")
    paths = (Path(d) / name for d in copybook_dirs for name in candidates)
    sidecar = next((p for p in paths if p.is_file()), None)
    if not sidecar:
        return {}
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    return {field["host_var"]: field for field in data["fields"]}


def _includes(spans: Sequence[Span]) -> Iterator[tuple[Span, str]]:
    """Yield ``(span, include_name)`` for each INCLUDE span."""
    parsed_spans = ((span, parse_exec_sql(span.parse_text)) for span in spans)
    return (
        (span, parsed.include.name)
        for span, parsed in parsed_spans
        if parsed.kind is Kind.INCLUDE and isinstance(parsed.include, IncludeName)
    )


def apply_sql_prepass(source: str, copybook_dirs: Sequence) -> PrepassResult:
    """Rewrite ``EXEC SQL INCLUDE <name> END-EXEC`` → ``COPY <name>.`` and load the
    dclgen JSON sidecars of the INCLUDE'd records in the same pass.

    All other EXEC SQL blocks and all ordinary COBOL text are returned
    byte-for-byte unchanged. *copybook_dirs* are searched for ``<NAME>.json``
    sidecars beside the copybooks ProLeap inlines; the gathered host-var metadata
    is returned in ``PrepassResult.field_meta`` (empty when none are present).
    """
    includes = list(_includes(find_exec_sql_spans(source)))
    field_meta = MappingProxyType(
        {
            host_var: descriptor
            for _span, include_name in includes
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
            (
                span.replace_start,
                span.replace_end,
                _rewrite_block(span.indent, include_name.upper()),
            )
            for span, include_name in includes
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
