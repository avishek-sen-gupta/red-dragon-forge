"""Unit guard: a COBOL step must fail loud when PROLEAP_BRIDGE_JAR is unset."""

from __future__ import annotations

import pytest

from jackal.allocation import DdEnvironment
from jackal.cobol_step import run_cobol_step
from tests.covers import NotLanguageFeature, covers
from tests.model_build import program


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_cobol_step_empty_bridge_jar_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="PROLEAP_BRIDGE_JAR"):
        run_cobol_step(
            program("S", "P"), "irrelevant", DdEnvironment(()), tmp_path, "", []
        )
