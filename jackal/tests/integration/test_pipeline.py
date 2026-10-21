from pathlib import Path

import pytest
from catnip.labels import RecordFormat, SequentialLabel
from interpreter.encoding.ebcdic_table import EbcdicTable
from interpreter.vm.builtins import core_builtins
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unknown_return_code import RaiseUnknownReturnCode
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import scratch, system, upload

FIX = Path(__file__).parent / "fixtures"
FB5 = SequentialLabel(RecordFormat.FB, 5)


def _ebcdic(text: bytes) -> bytes:
    """ASCII text -> its EBCDIC byte image (datasets are byte-faithful EBCDIC)."""
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_step_pipeline_transforms_through_intermediate(tmp_path, bridge_jar):
    upload(tmp_path, "J.IN", _ebcdic(b"applemango"), FB5)
    job = parse_jcl((FIX / "pipeline.jcl").read_text())
    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=package(tmp_path / "package", bridge_jar, ("UPCASE", "STARRER")),
        system=system(tmp_path),
        builtins=core_builtins(),
    )
    result = runner.run(job, scratch=scratch(tmp_path))
    datasets = tmp_path / "system" / "datasets"

    assert [s.name for s in result.steps] == ["STEP1", "STEP2"]
    assert all(s.outcome == Completed(0) for s in result.steps)
    # STEP1 transform (intermediate, PASSed): uppercased — EBCDIC byte image
    assert (datasets / "J.WORK").read_bytes() == _ebcdic(b"APPLEMANGO")
    # STEP2 transform (final): first byte of each 5-byte record starred — EBCDIC
    assert (datasets / "J.OUT").read_bytes() == _ebcdic(b"*PPLE*ANGO")
