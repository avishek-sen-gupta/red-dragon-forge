from pathlib import Path

import pytest

from jackal.jcl.parser import parse_jcl
from jackal.runner import JobRunner
from tests.covers import NotLanguageFeature, covers

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_step_pipeline_transforms_through_intermediate(tmp_path, bridge_jar):
    seed = tmp_path / "in.dat"
    seed.write_bytes(b"applemango")
    job = parse_jcl((FIX / "pipeline.jcl").read_text())
    runner = JobRunner(source_dir=FIX / "cbl", bridge_jar=bridge_jar)
    result = runner.run(job, workdir=tmp_path, seeds={"J.IN": seed})

    assert [s.name for s in result.steps] == ["STEP1", "STEP2"]
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    # STEP1 transform (intermediate, PASSed): uppercased
    assert (tmp_path / "J_WORK").read_bytes() == b"APPLEMANGO"
    # STEP2 transform (final): first byte of each 5-byte record starred
    assert (tmp_path / "J_OUT").read_bytes() == b"*PPLE*ANGO"
