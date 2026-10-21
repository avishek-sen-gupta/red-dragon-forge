"""Gating + path constants for the bms-tools pipeline.

hlasm_export is built from red-dragon's HLASM fork checkout at
vendor/red-dragon/hlasm-bridge/che4z.  bms_copybook_gen is a first-class
package in this repo — no PYTHONPATH manipulation needed.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_HLASM_FORK = _REPO_ROOT.parent / "vendor" / "red-dragon" / "hlasm-bridge" / "che4z"

HLASM_EXPORT_BIN: str | None = str(_HLASM_FORK / "build" / "bin" / "hlasm_export")

BMS_TOOLS_AVAILABLE: bool = bool(
    HLASM_EXPORT_BIN is not None and os.path.isfile(HLASM_EXPORT_BIN)
)
