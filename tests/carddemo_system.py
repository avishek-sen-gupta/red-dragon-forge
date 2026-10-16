"""CardDemo's data declaration installed into a system directory, for tests that start a region."""

from __future__ import annotations

from pathlib import Path

from catnip.declaration import load_declaration
from catnip.install import install
from catnip.system_catalog import SystemCatalog

_FORGE_ROOT = Path(__file__).parents[1]
_DECLARATION = _FORGE_ROOT / "config" / "carddemo" / "data.toml"


def installed_carddemo(root: Path) -> Path:
    system = root / "system"
    install(load_declaration(_DECLARATION), SystemCatalog(system))
    return system
