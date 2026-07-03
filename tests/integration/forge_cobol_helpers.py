"""Shared parser-construction helpers for red-dragon-forge integration tests.

Squall's own copybooks directory (SQLCA.cpy, DCLGEN records) must always be on
the parser's copybook search path whenever a SQL spec is in play — mirrors
Squall's own make_cobol_parser helper (tests/integration/squall_cobol_helpers.py).
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner


def squall_copybooks_dir() -> Path:
    """Return the filesystem path to squall's bundled copybooks (SQLCA, DCLGEN records)."""
    ref = importlib.resources.files("squall.copybooks")
    return Path(str(ref))


def make_parser(bridge_jar: str, copybook_dirs: list[Path] | None = None) -> ProLeapCobolParser:
    """Build a ProLeapCobolParser, always including squall's copybooks dir."""
    dirs: list[Path] = [squall_copybooks_dir()]
    if copybook_dirs:
        dirs.extend(copybook_dirs)
    return ProLeapCobolParser(RealSubprocessRunner(), bridge_jar, copybook_dirs=dirs)
