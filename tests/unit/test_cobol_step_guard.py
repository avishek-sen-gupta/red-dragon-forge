"""Unit guard: a COBOL step must fail loud when PROLEAP_BRIDGE_JAR is unset."""

from __future__ import annotations

import pytest

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import Step
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_cobol_step_empty_bridge_jar_fails_loud(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    step = Step(name="S", pgm="P", dds=())
    with pytest.raises(ValueError, match="PROLEAP_BRIDGE_JAR"):
        run_cobol_step(step, "irrelevant", cat, "", [])
