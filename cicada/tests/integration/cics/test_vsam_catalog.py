"""cicada's file control over the system catalog: one cluster, read through its path."""

from __future__ import annotations

import logging

import pytest

from catnip.system_catalog import SystemCatalog
from cics.vsam.engine import RESP_NORMAL, VsamEngine
from cics.vsam.eibresp import RESP_DUPKEY
from cics.vsam.file_table import FileTableError, cics_files
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.vsam_system import SeedAix, SeedCluster, build_test_system

_XREF = SeedCluster(
    "CCXREF",
    lrecl=8,
    key_length=3,
    records=(b"001AAAxx", b"002BBByy"),
    aix=(SeedAix("CXACAIX", key_offset=3, key_length=3, unique=False),),
)


@covers(CobolFeature.EXEC_CICS)
def test_a_record_written_through_the_cluster_is_read_through_its_path(tmp_path):
    system, dsnames = build_test_system(tmp_path, (_XREF,))
    engine = VsamEngine(cics_files(system, dsnames))

    wrote = engine.write("CCXREF", b"000", 3, b"000AAAzz")
    first = engine.read("CXACAIX", b"AAA", 3)
    restarted = VsamEngine(cics_files(SystemCatalog(tmp_path / "system"), dsnames))
    after_restart = restarted.read("CCXREF", b"000", 3)

    assert wrote == RESP_NORMAL
    assert first == (b"000AAAzz", RESP_DUPKEY)
    assert after_restart == (b"000AAAzz", RESP_NORMAL)


@covers(CobolFeature.EXEC_CICS)
def test_a_region_over_an_uncataloged_dsn_stops_at_startup(tmp_path):
    system, _ = build_test_system(tmp_path, (_XREF,))

    with pytest.raises(FileTableError) as error:
        cics_files(system, {"ACCTDAT": "NO.SUCH.KSDS"})

    assert str(error.value) == "CICS file ACCTDAT: NO.SUCH.KSDS is not cataloged"


@covers(CobolFeature.EXEC_CICS)
def test_a_key_shorter_than_declared_logs_both_lengths(tmp_path, caplog):
    system, dsnames = build_test_system(tmp_path, (_XREF,))
    engine = VsamEngine(cics_files(system, dsnames))

    with caplog.at_level(logging.WARNING, logger="cics.vsam.engine"):
        engine.read("CXACAIX", b"AA", 2)

    assert caplog.messages == [
        "CXACAIX (TEST.CCXREF.PATH): NOTFND; declared key 3 bytes at offset 3, program key 2 bytes"
    ]


@pytest.mark.xfail(
    reason="AIX duplicates come back in primary-key order, z/OS returns arrival order (red-dragon-forge-zqxf)",
    strict=True,
)
@covers(CobolFeature.EXEC_CICS)
def test_duplicate_alternate_keys_come_back_in_the_order_they_were_written(tmp_path):
    system, dsnames = build_test_system(tmp_path, (_XREF,))
    engine = VsamEngine(cics_files(system, dsnames))

    engine.write("CCXREF", b"000", 3, b"000AAAzz")
    first = engine.read("CXACAIX", b"AAA", 3)

    assert first == (b"001AAAxx", RESP_DUPKEY)
