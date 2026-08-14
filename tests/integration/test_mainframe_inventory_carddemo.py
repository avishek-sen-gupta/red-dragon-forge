# pyright: standard
"""The inventory must hold up on a real corpus, not just synthetic fixtures.

Anchored on facts independently verifiable in vendor/carddemo, and asserted as
lower bounds so adding jobs to the submodule does not break the suite.
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools"))

from mainframe_inventory import build_inventory  # noqa: E402

_CARDDEMO = _ROOT / "vendor" / "carddemo"

pytestmark = pytest.mark.skipif(
    not (_CARDDEMO / "app").is_dir(), reason="vendor/carddemo submodule not checked out"
)


@pytest.fixture(scope="module")
def inv():
    return build_inventory([_CARDDEMO])


def test_finds_the_batch_jobs_and_their_dominant_utility(inv):
    assert inv.counts["JCL.STMT.JOB"] >= 38
    assert inv.counts["TOOL.IDCAMS"] >= 60


def test_sdsf_appears_only_as_cics_region_console_glue(inv):
    """Every CardDemo SDSF deck is an MVS MODIFY to a CICS region — /F with
    CEMT SET FIL(..) CLO|OPE, or the spelled-out /MODIFY with SET PROG(..)
    NEWCOPY. Neither touches a dataset, which is what makes the step a
    skippable interlock rather than missing capability."""
    sdsf = {
        key.split("TOOL.SDSF.")[1]
        for key in inv.counts
        if key.startswith("TOOL.SDSF.") and key != "TOOL.SDSF.UNREGISTERED"
    }
    assert sdsf == {"F", "F.FIL", "MODIFY", "MODIFY.PROG"}


def test_finds_the_alternate_index_toolchain_that_blocks_tier_three_jobs(inv):
    for verb in ("DEFINE_ALTERNATEINDEX", "DEFINE_PATH", "BLDINDEX"):
        assert inv.counts[f"TOOL.IDCAMS.{verb}"] > 0, verb


def test_finds_generation_data_group_definitions(inv):
    assert inv.counts["TOOL.IDCAMS.DEFINE_GENERATIONDATAGROUP"] > 0
    assert inv.counts["JCL.DSN.GDG_RELATIVE"] > 0


def test_finds_the_ims_and_tso_batch_surface(inv):
    """The IMS/Db2/MQ subtree is real JCL the batch-job analysis never covered."""
    assert inv.counts["TOOL.DFSRRC00"] > 0
    assert inv.counts["TOOL.IKJEFT01"] > 0


def test_finds_the_online_cics_surface(inv):
    assert inv.counts["CICS.SEND_MAP"] > 0
    assert inv.counts["CICS.AREA.FILE_CONTROL"] > 0
    assert inv.counts["BMS.DFHMSD"] > 0
