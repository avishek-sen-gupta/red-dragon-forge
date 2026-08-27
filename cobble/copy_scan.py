"""copy_scan.py — every COPY a corpus names, without resolving any of them.

The expensive phase of a corpus build is COBOL parsing: one JVM per program,
thousands of programs, and a COPY the ProLeap preprocessor cannot resolve fails
that whole program. Resolution is therefore the step worth asking about first,
and it is also the only step that needs a copybook on disk.

ProLeap splits preprocessing into readLines / rewriteLines / parseDocument, and
COPY resolution lives only in the last of those. Its ``CobolPreprocessor.g4``
grammar recognises ``copyStatement`` by itself, upstream of any resolution, so
the bridge's ``-scan-copy`` mode parses with that grammar alone: no copybook
directory is read, no ASG is built, and one JVM handles the whole corpus.

Using the grammar rather than a scanner of our own is not incidental. Its
STRINGLITERAL rule excludes newlines, so a quote left unterminated by
fixed-format continuation degrades to a token the grammar absorbs and the parse
walks on. A light scanner whose string rule spans newlines instead pairs that
opening quote with the continuation line's resume quote and goes blind for the
rest of the file -- on one production corpus that silently lost 328 of 3779
members, every COPY in them included.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from cobble.interpreter.cobol.subprocess_runner import (
    RealSubprocessRunner,
    SubprocessRunner,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CopyRef:
    """One COPY statement: the copybook name as written, and its 1-based line."""

    name: str
    line: int


@dataclass(frozen=True)
class ScanResult:
    """One scanned member.

    ``errors`` counts the syntax errors ANTLR reported. It is not fatal: ANTLR
    recovers and keeps reporting COPYs afterwards, so a non-zero count means
    ``copies`` may be incomplete, not that it is empty. ``message`` is set only
    when the member could not be read at all.
    """

    path: Path
    copies: tuple[CopyRef, ...]
    errors: int
    message: str | None = None


def scan_copy_statements(
    paths: Sequence[Path],
    runner: SubprocessRunner,
    bridge_jar: str,
) -> list[ScanResult]:
    """Scan every path in one bridge invocation.

    One JVM for the whole corpus is the point: per member, JVM startup dominates
    everything the scan itself does. An empty list starts nothing.
    """
    if not paths:
        return []
    command = ["java", "-jar", bridge_jar, "-scan-copy"]
    stdin = "".join(f"{path}\n" for path in paths)
    logger.debug("Scanning %d member(s) for COPY statements", len(paths))
    return list(_parse_json_lines(runner.run(command, stdin).splitlines()))


def _parse_json_lines(lines: Iterable[str]) -> Iterable[ScanResult]:
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        yield ScanResult(
            path=Path(row["file"]),
            copies=tuple(
                CopyRef(name=copy["name"], line=copy["line"]) for copy in row["copies"]
            ),
            errors=row["errors"],
            message=row.get("message"),
        )


def make_copy_scanner() -> tuple[SubprocessRunner, str]:
    """The runner and bridge jar path to hand :func:`scan_copy_statements`.

    Falls back to the canonical build output path when PROLEAP_BRIDGE_JAR is
    unset, matching :func:`cobble.interpreter.cobol.cobol_parser.make_cobol_parser`.
    """
    bridge_jar = os.environ.get(
        "PROLEAP_BRIDGE_JAR",
        "proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar",
    )
    return RealSubprocessRunner(), bridge_jar
