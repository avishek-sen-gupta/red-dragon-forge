"""Genuine end-to-end execution tests for the (execution-wired) IDCAMS
path against real CardDemo JCL.

Unlike the unit tests in tests/unit/test_idcams_executor.py (which feed
hand-written command sequences to run_idcams), these read the REAL .jcl
file bytes off disk, parse them through the real jcl-bridge (parse_jcl),
extract the actual IDCAMS SYSIN in-stream the bridge produced, and run it
through parse_idcams -> run_idcams -- asserting the VSAM dataset really
gets built in the simulated catalog. No transcription: if the real file's
bridge-extracted text differs in any way from what a human would type, it
is exercised here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.idcams.executor import run_idcams
from jackal.idcams.parser import parse_idcams
from jackal.jcl.parser import parse_jcl
from jackal.dsn import DdName
from jackal.model import DatasetOrg, ProgramRef, ProgramStep
from tests.covers import NotLanguageFeature, covers


def _idcams_sysin_blocks(job) -> list[str]:
    """Every IDCAMS step's SYSIN in-stream text, in job order."""
    blocks: list[str] = []
    for step in job.steps:
        if not isinstance(step, ProgramStep) or step.pgm != ProgramRef("IDCAMS"):
            continue
        for dd in step.dds:
            if dd.ddname == DdName("SYSIN") and dd.in_stream:
                blocks.append("\n".join(dd.in_stream) + "\n")
    return blocks


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cbexport_step01_builds_export_cluster_end_to_end(
    tmp_path: Path, carddemo_home: Path, jcl_bridge_jar: str
):
    """Read the real CBEXPORT.jcl, run its STEP01 IDCAMS block
    (DELETE...CLUSTER PURGE / SET MAXCC=0 / DEFINE CLUSTER with DATA/INDEX
    trailers) through the execution-wired path, and confirm the export
    KSDS is actually registered in the catalog with the DEFINE's real
    KEYS/RECORDSIZE."""
    job = parse_jcl((carddemo_home / "jcl" / "CBEXPORT.jcl").read_text())
    blocks = _idcams_sysin_blocks(job)
    assert len(blocks) == 1, "CBEXPORT.jcl is expected to have exactly one IDCAMS step"

    catalog = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    rc = run_idcams(parse_idcams(blocks[0]), (), catalog)
    assert rc == 0

    ds = catalog.resolve("AWS.M2.CARDDEMO.EXPORT.DATA")
    assert ds.org is DatasetOrg.KSDS
    assert ds.key_length == 4
    assert ds.key_offset == 28
    assert ds.record_size == 500
