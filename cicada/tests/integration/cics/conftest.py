"""Gate for the CardDemo end-to-end CICS tests.

These exercise the real unmodified CardDemo COBOL through the full toolchain
(CardDemo submodule + bms-tools submodule + a built ProLeap JAR). Modules opt in
with ``pytestmark = pytest.mark.carddemo_e2e``.

Policy: run everywhere (CI and local) when the toolchain is available, fail with
setup guidance when it is not. No silent skips — a missing tool must never hide
a regression.

Resolution order for CARDDEMO_HOME:
  1. CARDDEMO_HOME env var (explicit override, set by CI workflow)
  2. vendor/carddemo/app submodule (auto-detected from the monorepo root,
     shared with jackal -- see vendor/carddemo)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from catnip.declaration import load_declaration
from catnip.install import install
from catnip.system_catalog import SystemCatalog
from tests.integration.cics.bms_tools_helpers import BMS_TOOLS_AVAILABLE

_MONOREPO_ROOT = Path(__file__).parents[4]
_SUBMODULE_CARDDEMO = _MONOREPO_ROOT / "vendor" / "carddemo" / "app"
_DATA_DECLARATION = _MONOREPO_ROOT / "config" / "carddemo" / "data.toml"


def _resolve_carddemo_home() -> str | None:
    if env := os.environ.get("CARDDEMO_HOME"):
        return env
    if _SUBMODULE_CARDDEMO.is_dir():
        return str(_SUBMODULE_CARDDEMO)
    return None


_CARDDEMO_HOME = _resolve_carddemo_home()

if _CARDDEMO_HOME:
    os.environ.setdefault("CARDDEMO_HOME", _CARDDEMO_HOME)

_TOOLCHAIN_OK = bool(_CARDDEMO_HOME) and BMS_TOOLS_AVAILABLE

_SETUP_MSG = (
    "CardDemo e2e toolchain not available. Ensure:\n"
    "  • git submodule update --init --recursive vendor/carddemo vendor/red-dragon\n"
    "  • ProLeap JAR built: cd proleap-bridge && mvn -DskipTests package\n"
    "  • hlasm_export built (make hlasm) into "
    "vendor/red-dragon/hlasm-bridge/che4z/build/bin/"
)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("carddemo_e2e") is None:
        return
    if not _TOOLCHAIN_OK:
        pytest.fail(_SETUP_MSG, pytrace=False)


@pytest.fixture
def carddemo_system(tmp_path: Path) -> Path:
    """CardDemo's data declaration installed into a fresh system directory."""
    system = tmp_path / "system"
    install(load_declaration(_DATA_DECLARATION), SystemCatalog(system))
    return system
