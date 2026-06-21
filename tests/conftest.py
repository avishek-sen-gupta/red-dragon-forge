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


@pytest.fixture
def carddemo_home() -> Path:
    """Root of the CardDemo checkout; skip if CARDDEMO_HOME is unset."""
    home = os.environ.get("CARDDEMO_HOME")
    if not home:
        pytest.skip("CARDDEMO_HOME not set")
    return Path(home)
