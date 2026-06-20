import os

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path; fail loudly if unset (COBOL steps need it)."""
    jar = os.environ["PROLEAP_BRIDGE_JAR"]
    assert jar, "PROLEAP_BRIDGE_JAR must point at the built bridge JAR"
    return jar
