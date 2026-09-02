"""Shared parser-construction helpers for red-dragon-forge integration tests.

Squall's own copybooks directory (SQLCA.cpy, DCLGEN records) must always be on
the parser's copybook search path whenever a SQL spec is in play — mirrors
Squall's own make_cobol_parser helper (tests/integration/squall_cobol_helpers.py).

Cicada's CICS copybooks directory (DFHEIBLK.cpy) must likewise always be on the
search path whenever a CICS spec is in play: the CICS lowering prepass injects
`COPY DFHEIBLK.` into WORKING-STORAGE (see `test_cics_adapter.py`), and ProLeap
only resolves that copybook if this directory is on the path. A test combining
CICS and SQL specs (as in `test_cics_sql_composition.py`) needs both copybook
directories present at once — a gap neither adapter's own isolated test surfaces
on its own, since each only ever exercised its own copybook dir.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import cics
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner


def squall_copybooks_dir() -> Path:
    """Return the filesystem path to squall's bundled copybooks (SQLCA, DCLGEN records)."""
    ref = importlib.resources.files("squall.copybooks")
    return Path(str(ref))


def cics_copybooks_dir() -> Path:
    """Return the filesystem path to cicada's bundled CICS copybooks (DFHEIBLK)."""
    return Path(cics.__file__).parent / "copybooks"


def make_parser(
    bridge_jar: str, copybook_dirs: list[Path] | None = None
) -> ProLeapCobolParser:
    """Build a ProLeapCobolParser, always including squall's and cics's copybooks dirs."""
    dirs: list[Path] = [squall_copybooks_dir(), cics_copybooks_dir()]
    if copybook_dirs:
        dirs.extend(copybook_dirs)
    return ProLeapCobolParser(RealSubprocessRunner(), bridge_jar, copybook_dirs=dirs)
