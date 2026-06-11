"""Gating + path constants for the bms-tools pipeline.

hlasm_export is built from the HLASM fork submodule at
third-party/che-che4z-lsp-for-hlasm-fork.  bms_copybook_gen is a first-class
package in this repo — no PYTHONPATH manipulation needed.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_HLASM_FORK = _REPO_ROOT / "third-party" / "che-che4z-lsp-for-hlasm-fork"

HLASM_EXPORT_BIN: str | None = str(_HLASM_FORK / "build" / "bin" / "hlasm_export")

BMS_TOOLS_AVAILABLE: bool = bool(
    HLASM_EXPORT_BIN is not None and os.path.isfile(HLASM_EXPORT_BIN)
)
