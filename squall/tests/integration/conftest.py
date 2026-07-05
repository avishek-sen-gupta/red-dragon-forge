"""Integration test configuration and shared fixtures for squall.

Defines the bridge_jar fixture so that integration tests can request it
without an absolute import that conflicts with the vendored red-dragon
tests package (which also has a tests.integration namespace).
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """Return the ProLeap bridge JAR path from the required PROLEAP_BRIDGE_JAR env.

    No default, no skip: a missing env var raises KeyError so tests cannot
    silently succeed without the real JAR present.
    """
    return os.environ["PROLEAP_BRIDGE_JAR"]
