"""path_utils.py — one place for the expand-env-vars + expand-user pattern.

Every config loader that reads a path string from a TOML file calls this so
that $CC_ROOT (or any other env var) is expanded before the path is used.
"""

from __future__ import annotations

import os
from pathlib import Path


def config_path(text: str) -> Path:
    """Expand environment variables and ~ in a TOML path string."""
    return Path(os.path.expandvars(text)).expanduser()
