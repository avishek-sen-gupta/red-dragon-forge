"""cobol_harness: reusable primitives for compiling and driving a real
COBOL/CICS program through RedDragon/cicada, headless, for execution-
grounded testing/investigation.

Four groups, matching the four concerns any such harness has:

  - **compile**: get the program (and whatever it EXEC CICS LINKs to)
    compiled and registered. See ``compile.compile_main_program``,
    ``compile.compile_link_targets``, ``compile.make_noop_stub_source``.
  - **region** (``CicsSession``): drive the CICS side headless -- one turn
    at a time, via ``start_turn``/``step_turn``, draining whatever screens
    the program SEND MAPped.
  - **vsam** + **commarea**: set up test data -- byte-exact VSAM seed
    records (``vsam.build_record``, piggybacking on COBOL's own INITIALIZE
    semantics) and COMMAREA buffers (``commarea.build_commarea``), both
    resolved by field name through the program's own ``data_layout``, not
    hand-computed offsets.
  - **state**: assert on the final result -- read a field off a rendered
    screen (``state.screen_field``) or straight out of WORKING-STORAGE
    (``state.read_vm_field``).

None of these modules know anything about any specific program --
every program-specific detail (which copybooks, which datasets, which
LINK targets, which screen fields) is supplied by the caller.

Requires running inside cicada's own venv (``cd
$FORGE_ROOT/cicada && uv run python3 ...``) -- cicada's venv has the
``antlr4`` dependency cicada's CICS statement parser needs; red-dragon's
own venv does not. Also requires ``FORGE_ROOT/vendor/red-dragon`` and
``FORGE_ROOT/cicada`` on ``sys.path`` before importing anything from this
package -- see ``bootstrap_paths``.
"""
from __future__ import annotations

import sys
from pathlib import Path


def bootstrap_paths(forge_root: Path) -> None:
    """Insert cicada and red-dragon onto sys.path. Call this BEFORE
    importing anything else from this package or from ``cics``/
    ``interpreter`` -- it's not automatic on package import because the
    forge checkout location varies by caller (env var, default, etc.) and
    doing it as an import side effect would make that implicit."""
    forge_root = Path(forge_root)
    for sub in ("cicada", "vendor/red-dragon"):
        p = str(forge_root / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
