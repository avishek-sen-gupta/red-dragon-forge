"""
squall.dclgen_copybooks
~~~~~~~~~~~~~~~~~~~~~~~~
Model the Db2 precompiler's one relevant step for real IBM DCLGEN copybooks:
strip the ``EXEC SQL DECLARE <table> TABLE (...) END-EXEC.`` preamble that a
real precompiler consumes before the COBOL compiler ever sees the source.

Real IBM DCLGEN copybooks carry this preamble alongside the host-variable
record; a Db2 precompiler consumes it and the COBOL compiler never sees it.
ProLeap owns ``COPY`` expansion and its grammar has no place for ``EXEC SQL``
inside a DATA DIVISION, so without this step ProLeap rejects the copybook the
moment it is inlined. squall's own ``dclgen.py`` never emits this preamble (it
generates only the host-variable record), so this had never been exercised
until real DCLGEN copybooks — e.g. CardDemo's ``dcl/*.dcl`` — entered the
pipeline.

Design
------
* ``stage_sanitised_copybooks`` is the only public entry point. Nothing calls
  it in production yet — see ``forge-9ow`` for wiring it into a real
  ``copybook_dirs`` list.
* The regex matches ``DECLARE ... TABLE ... END-EXEC`` specifically. It must
  never match ``DECLARE ... CURSOR``, a real executable SQL statement that has
  to survive untouched.
* File I/O (copying, reading, writing) is inherently effectful; the stripping
  itself is a pure string transform (``_strip_declare_table``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

_DECLARE_TABLE: Final[re.Pattern[str]] = re.compile(
    r"(?is)^[^\S\n]*(?:\d{6})?[^\S\n]*EXEC\s+SQL\s+DECLARE\s+[\w.$#@-]+\s+TABLE\b"
    r"(?:(?!\bEND-EXEC\b).)*?\bEND-EXEC\b[^\S\n]*\.?[^\S\n]*$\n?",
    re.MULTILINE,
)


def _strip_declare_table(text: str) -> str:
    """Remove any ``EXEC SQL DECLARE ... TABLE ... END-EXEC.`` block from *text*.

    Never touches ``EXEC SQL DECLARE ... CURSOR ...``, which is a real
    executable statement, not a precompiler-only declaration.
    """
    return _DECLARE_TABLE.sub("", text)


def _source_files(source_dirs: Sequence[Path]) -> Iterator[Path]:
    """Yield every file across *source_dirs*, in precedence order (first wins)."""
    return (
        entry
        for source_dir in source_dirs
        for entry in sorted(source_dir.iterdir())
        if entry.is_file()
    )


def _first_occurrence(entries: Iterator[Path]) -> Iterator[Path]:
    """Keep only the first entry for each filename, in *entries*' own order.

    Built by folding right-to-left: a dict comprehension over the reversed
    sequence lets the true first occurrence be assigned last for its key,
    so it is the one left standing — no mutation loop needed to track
    "already seen" names.
    """
    return iter({entry.name: entry for entry in reversed(list(entries))}.values())


def _stage_one(src: Path, out_dir: Path) -> None:
    """Write the sanitised copy of *src* into *out_dir*, overwriting any stale copy.

    Reads and writes as ``latin-1`` — the byte-identity codec for vendored,
    EBCDIC-era COBOL sources, so a member's high bytes round-trip unchanged
    instead of raising ``UnicodeDecodeError`` under ``utf-8``.
    """
    dest = out_dir / src.name
    dest.write_text(
        _strip_declare_table(src.read_text(encoding="latin-1")), encoding="latin-1"
    )


def stage_sanitised_copybooks(source_dirs: Sequence[Path], out_dir: Path) -> Path:
    """Copy every copybook from *source_dirs* into *out_dir*, stripping any
    ``EXEC SQL DECLARE ... TABLE ... END-EXEC.`` block along the way.

    Models the Db2 precompiler step that consumes ``DECLARE TABLE`` before the
    COBOL compiler sees the source. *source_dirs* are processed in order, and
    when the same filename appears in more than one, the first directory wins
    — matching ``copybook_dirs`` precedence, so callers can place this
    function's return value first to shadow the untouched originals. Every
    staged file is written fresh on each call — a stale file left over in
    *out_dir* from an earlier call is never allowed to silently shadow a real
    copybook.

    Returns *out_dir* (created if it does not already exist).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for entry in _first_occurrence(_source_files(source_dirs)):
        _stage_one(entry, out_dir)
    return out_dir
