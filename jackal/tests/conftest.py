import os
from pathlib import Path

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path; fail loudly if unset (COBOL steps need it)."""
    jar = os.environ["PROLEAP_BRIDGE_JAR"]
    assert jar, "PROLEAP_BRIDGE_JAR must point at the built bridge JAR"
    return jar


@pytest.fixture
def jcl_bridge_jar() -> str:
    """The jcl-bridge JAR path; fail loudly if unset."""
    jar = os.environ["JCL_BRIDGE_JAR"]
    assert jar, "JCL_BRIDGE_JAR must point at the built jcl-bridge JAR"
    return jar


_SUBMODULE_CARDDEMO = (
    Path(__file__).resolve().parents[2] / "vendor" / "carddemo" / "app"
)


@pytest.fixture
def carddemo_home() -> Path:
    """CardDemo's app/ directory: CARDDEMO_HOME if set, else forge's vendor/carddemo
    submodule; skip only when neither exists."""
    home = Path(os.environ.get("CARDDEMO_HOME", _SUBMODULE_CARDDEMO))
    if not home.is_dir():
        pytest.skip(f"no CardDemo checkout at {home}")
    return home
