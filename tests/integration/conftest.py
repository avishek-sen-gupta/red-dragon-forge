"""Shared fixtures for red-dragon-forge integration tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path — required, no default, no skip."""
    return os.environ["PROLEAP_BRIDGE_JAR"]
