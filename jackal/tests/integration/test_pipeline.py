from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers

FIX = Path(__file__).parent / "fixtures"


def _ebcdic(text: bytes) -> bytes:
    """ASCII text -> its EBCDIC byte image (datasets are byte-faithful EBCDIC)."""
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_step_pipeline_transforms_through_intermediate(tmp_path, bridge_jar):
    seed = tmp_path / "in.dat"
    seed.write_bytes(_ebcdic(b"applemango"))
    job = parse_jcl((FIX / "pipeline.jcl").read_text())
    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        source_dir=FIX / "cbl",
        bridge_jar=bridge_jar,
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    result = runner.run(job, workdir=tmp_path, seeds={"J.IN": seed})

    assert [s.name for s in result.steps] == ["STEP1", "STEP2"]
    assert all(s.outcome == Completed(0) for s in result.steps)
    # STEP1 transform (intermediate, PASSed): uppercased — EBCDIC byte image
    assert (tmp_path / "J_WORK").read_bytes() == _ebcdic(b"APPLEMANGO")
    # STEP2 transform (final): first byte of each 5-byte record starred — EBCDIC
    assert (tmp_path / "J_OUT").read_bytes() == _ebcdic(b"*PPLE*ANGO")
