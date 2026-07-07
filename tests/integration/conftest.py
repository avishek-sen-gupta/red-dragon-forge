"""Shared fixtures for red-dragon-forge integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path — required, no default, no skip."""
    return os.environ["PROLEAP_BRIDGE_JAR"]


@pytest.fixture
def jcl_bridge_jar() -> str:
    """The jcl-bridge JAR path — required, no default, no skip."""
    return os.environ["JCL_BRIDGE_JAR"]


@pytest.fixture
def carddemo_home() -> Path:
    """Root of the CardDemo checkout. Uses jackal's own vendored copy by
    default (it has cbl/, cpy/, csd/, and jcl/ all present, avoiding any
    cross-checkout inconsistency); CARDDEMO_HOME overrides."""
    env = os.environ.get("CARDDEMO_HOME")
    if env:
        return Path(env)
    default = Path(__file__).parents[2] / "jackal" / "third-party" / "carddemo" / "app"
    if not default.is_dir():
        pytest.skip(f"CardDemo checkout not found at {default}; set CARDDEMO_HOME")
    return default
