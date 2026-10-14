"""CardDemo's data declaration installed into a system directory, for tests that start a region."""

from __future__ import annotations

from pathlib import Path

from catnip.declaration import load_declaration
from catnip.install import install
from catnip.system_catalog import SystemCatalog

_FORGE_ROOT = Path(__file__).parents[1]
_DECLARATION = _FORGE_ROOT / "config" / "carddemo" / "data.toml"


def installed_carddemo(root: Path) -> Path:
    declaration = root / "data.toml"
    declaration.write_text(
        _DECLARATION.read_text().replace("${FORGE_ROOT}", str(_FORGE_ROOT))
    )
    system = root / "system"
    install(load_declaration(declaration), SystemCatalog(system))
    return system


def region_toml(config: Path, system: Path) -> Path:
    region = system.parent / config.name
    region.write_text(
        config.read_text().replace(
            'system = "/tmp/carddemo-system"', f'system = "{system}"'
        )
    )
    return region
