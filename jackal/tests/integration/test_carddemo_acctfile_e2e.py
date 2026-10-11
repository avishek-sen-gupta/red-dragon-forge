"""End-to-end test: ACCTFILE.jcl (IDCAMS build KSDS) then READACCT.jcl (CBACT01C)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.catalog import DatasetCatalog
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from tests.covers import NotLanguageFeature, covers


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_acctfile_then_readacct_e2e(
    tmp_path: Path, carddemo_home: Path, bridge_jar: str
) -> None:
    """Run ACCTFILE.jcl (DELETE+DEFINE+REPRO) then READACCT.jcl (CBACT01C).

    Both jobs share a single DatasetCatalog so the KSDS built by ACCTFILE
    is visible to CBACT01C in READACCT.
    """
    # CARDDEMO_HOME already points at the "app" subdirectory of the checkout.
    # Layout: $CARDDEMO_HOME/jcl/, $CARDDEMO_HOME/cbl/, $CARDDEMO_HOME/cpy/,
    #         $CARDDEMO_HOME/data/EBCDIC/
    jcl_dir = carddemo_home / "jcl"
    cbl_dir = carddemo_home / "cbl"
    cpy_dir = carddemo_home / "cpy"
    data_dir = carddemo_home / "data" / "EBCDIC"

    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        source_dir=cbl_dir,
        bridge_jar=bridge_jar,
        data_dir=data_dir,
        copybook_dir=cpy_dir,
    )

    catalog = DatasetCatalog(workdir=tmp_path, data_dir=data_dir)

    # --- Phase 1: ACCTFILE.jcl -- DELETE old KSDS, DEFINE new KSDS, REPRO PS→KSDS ---
    acctfile_job = parse_jcl((jcl_dir / "ACCTFILE.jcl").read_text())
    acctfile_result = runner.run_job(acctfile_job, catalog)

    assert [s.name for s in acctfile_result.steps] == ["STEP05", "STEP10", "STEP15"]
    assert all(
        s.outcome == Completed(0) for s in acctfile_result.steps
    ), f"ACCTFILE steps failed: {[(s.name, s.outcome) for s in acctfile_result.steps]}"

    # KSDS backing file must exist and be non-empty after REPRO
    ksds_dsn = "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"
    ksds_ds = catalog.resolve(ksds_dsn)
    assert ksds_ds.path.exists(), f"KSDS backing file not found: {ksds_ds.path}"
    assert ksds_ds.path.stat().st_size > 0, "KSDS backing file is empty after REPRO"

    # --- Phase 2: READACCT.jcl -- CBACT01C reads KSDS, writes OUTFILE ---
    readacct_job = parse_jcl((jcl_dir / "READACCT.jcl").read_text())
    readacct_result = runner.run_job(readacct_job, catalog)

    # READACCT has PREDEL (IEFBR14) + STEP05 (CBACT01C)
    step_names = [s.name for s in readacct_result.steps]
    assert (
        "STEP05" in step_names
    ), f"Expected STEP05 in READACCT steps, got {step_names}"
    assert all(
        s.outcome == Completed(0) for s in readacct_result.steps
    ), f"READACCT steps failed: {[(s.name, s.outcome) for s in readacct_result.steps]}"

    # CBACT01C writes OUTFILE (DSN=AWS.M2.CARDDEMO.ACCTDATA.PSCOMP)
    outfile_dsn = "AWS.M2.CARDDEMO.ACCTDATA.PSCOMP"
    outfile_ds = catalog.resolve(outfile_dsn)
    assert outfile_ds.path.exists(), f"OUTFILE not found: {outfile_ds.path}"
    assert outfile_ds.path.stat().st_size > 0, "OUTFILE is empty"

    # First 11 bytes of OUTFILE (EBCDIC) must decode to first account id
    first_11 = outfile_ds.path.read_bytes()[:11]
    decoded = EbcdicTable.ebcdic_to_ascii(first_11)
    assert (
        decoded == b"00000000001"
    ), f"First account id mismatch: expected b'00000000001', got {decoded!r}"
