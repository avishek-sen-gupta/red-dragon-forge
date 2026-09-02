"""Tests for the IDCAMS executor."""

from __future__ import annotations

from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.dsn import DirectDSN
from jackal.idcams.commands import DefineCluster, Delete, IfMaxcc, Repro, SetMaxcc
from jackal.model import DD, Disp, DispNormal, DispStatus
from jackal.value_parts import literal
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_loads_ps_into_ksds(tmp_path):
    from jackal.idcams.executor import run_idcams

    data = tmp_path / "data"
    data.mkdir()
    (data / "IN.PS").write_bytes(b"AAArec1xxBBBrec2xx")  # two 9-byte records, key=3@0
    cat = DatasetCatalog(workdir=tmp_path / "wd", data_dir=data)
    (tmp_path / "wd").mkdir()
    dds = (
        DD(
            "INF",
            DirectDSN(literal("IN.PS")),
            Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
        ),
        DD(
            "OUT",
            DirectDSN(literal("OUT.KSDS")),
            Disp(DispStatus.OLD, DispNormal.KEEP, DispNormal.KEEP),
        ),
    )
    cmds = (
        DefineCluster(name="OUT.KSDS", key_length=3, key_offset=0, record_size=9),
        Repro(infile_dd="INF", outfile_dd="OUT"),
    )
    rc = run_idcams(cmds, dds, cat)
    assert rc == 0
    # read OUT.KSDS back via the IndexedDriver and confirm BBB record present
    from interpreter.cobol.file_drivers import IndexedDriver
    from cobol_asg.file_enums import OpenMode

    drv = IndexedDriver()
    drv.open(cat.resolve("OUT.KSDS").path, OpenMode.INPUT, 9, 0, 3)
    assert drv.read_key(b"BBB").data[:3] == b"BBB"
    drv.close()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_existing_dsn_returns_0(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    (tmp_path / "MY_DS").write_bytes(b"")
    cat.seed("MY.DS", tmp_path / "MY_DS")
    cmds = (Delete(dsn="MY.DS"),)
    rc = run_idcams(cmds, (), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_missing_dsn_returns_8(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cmds = (Delete(dsn="GHOST.DS"),)
    rc = run_idcams(cmds, (), cat)
    assert rc == 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_registers_in_catalog(tmp_path):
    from jackal.idcams.executor import run_idcams
    from jackal.model import DatasetOrg

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cmds = (DefineCluster(name="MY.KSDS", key_length=5, key_offset=0, record_size=80),)
    rc = run_idcams(cmds, (), cat)
    assert rc == 0
    ds = cat.resolve("MY.KSDS")
    assert ds.org is DatasetOrg.KSDS
    assert ds.key_length == 5
    assert ds.record_size == 80


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_sets_value_when_condition_met(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    # Delete missing → maxcc=8; IfMaxcc LE 8 → set maxcc=0
    cmds = (
        Delete(dsn="GHOST.DS"),
        IfMaxcc(op="LE", value=8, set_value=0),
    )
    rc = run_idcams(cmds, (), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_does_not_set_when_condition_not_met(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    # Delete missing → maxcc=8; IfMaxcc LT 8 → not met (8 < 8 is false)
    cmds = (
        Delete(dsn="GHOST.DS"),
        IfMaxcc(op="LT", value=8, set_value=0),
    )
    rc = run_idcams(cmds, (), cat)
    assert rc == 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_all_operators():
    from jackal.idcams.executor import _handle_if_maxcc

    # predicate true -> set_value
    assert _handle_if_maxcc(IfMaxcc(op="GE", value=8, set_value=0), 8) == 0
    assert _handle_if_maxcc(IfMaxcc(op="GT", value=4, set_value=0), 8) == 0
    assert _handle_if_maxcc(IfMaxcc(op="EQ", value=8, set_value=0), 8) == 0
    assert _handle_if_maxcc(IfMaxcc(op="NE", value=0, set_value=0), 8) == 0
    # predicate false -> maxcc unchanged
    assert _handle_if_maxcc(IfMaxcc(op="GT", value=8, set_value=0), 8) == 8
    assert _handle_if_maxcc(IfMaxcc(op="EQ", value=4, set_value=0), 8) == 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_maxcc_overrides_accumulated_rc(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    # Delete missing -> maxcc=8; a bare SET MAXCC=0 forcibly overrides it,
    # same idempotency idiom real CardDemo JCL uses so a missing dataset
    # doesn't fail a step that's about to (re)DEFINE it anyway.
    cmds = (
        Delete(dsn="GHOST.DS"),
        SetMaxcc(value=0),
    )
    rc = run_idcams(cmds, (), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_lastcc_tests_immediately_preceding_command_rc(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cmds = (
        Delete(dsn="GHOST.DS"),  # missing -> rc 8, lastcc=8, maxcc=8
        IfMaxcc(op="EQ", value=8, set_value=0, test_field="LASTCC"),
    )
    rc = run_idcams(cmds, (), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_lastcc_reflects_only_the_most_recent_command_not_running_maxcc(tmp_path):
    """LASTCC and MAXCC are genuinely distinct: a later, successful command
    resets LASTCC to 0 even though MAXCC still remembers an earlier
    failure. A test asserting against the wrong counter would give 8
    here instead of 99."""
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cmds = (
        Delete(dsn="GHOST.DS"),  # missing -> rc 8; lastcc=8, maxcc=8
        DefineCluster(
            name="MY.KSDS", key_length=5, key_offset=0, record_size=80
        ),  # succeeds -> rc 0; lastcc=0, maxcc stays 8 (max(8,0))
        IfMaxcc(op="EQ", value=0, set_value=99, test_field="LASTCC"),
    )
    rc = run_idcams(cmds, (), cat)
    assert rc == 99


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_maxcc_does_not_change_lastcc(tmp_path):
    """Per the manual: 'Setting MAXCC does not affect LASTCC.' A SET
    MAXCC=n between two functional commands must not corrupt the next
    IF LASTCC test."""
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cmds = (
        Delete(dsn="GHOST.DS"),  # missing -> rc 8; lastcc=8, maxcc=8
        SetMaxcc(value=0),  # maxcc forced to 0; lastcc still 8
        IfMaxcc(op="EQ", value=8, set_value=99, test_field="LASTCC"),
    )
    rc = run_idcams(cmds, (), cat)
    assert rc == 99


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_purge_flag_deletes_existing_dsn_same_as_without_purge(tmp_path):
    """No retention/expiration tracking exists in this simulated catalog
    today, so PURGE is currently a documented no-op: parsing/execution
    must not crash, and behavior matches an equivalent non-PURGE delete."""
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    (tmp_path / "MY_DS").write_bytes(b"")
    cat.seed("MY.DS", tmp_path / "MY_DS")
    cmds = (Delete(dsn="MY.DS", purge=True),)
    rc = run_idcams(cmds, (), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_purge_set_define_sequence_executes(tmp_path):
    """A representative (hand-written) multi-statement block in the shape
    CBEXPORT.jcl's STEP01 uses: DELETE...CLUSTER PURGE, standalone
    SET MAXCC=0, then DEFINE CLUSTER with DATA/INDEX trailers and several
    ignored SMS-style params. This is a fast unit test with NO real-file
    read -- the genuine end-to-end test that reads the real CBEXPORT.jcl
    bytes through the jcl-bridge lives in
    tests/integration/test_idcams_execution_carddemo_e2e.py."""
    from jackal.idcams.parser import parse_idcams
    from jackal.idcams.executor import run_idcams

    text = (
        "  DELETE AWS.M2.CARDDEMO.EXPORT.DATA CLUSTER PURGE\n"
        "  SET MAXCC = 0\n"
        "  DEFINE CLUSTER (NAME(AWS.M2.CARDDEMO.EXPORT.DATA) -\n"
        "                  INDEXED -\n"
        "                  KEYS(4 28) -\n"
        "                  RECORDSIZE(500 500) -\n"
        "                  CYLINDERS(10 5) -\n"
        "                  FREESPACE(10 10) -\n"
        "                  SHAREOPTIONS(2 3)) -\n"
        "         DATA (NAME(AWS.M2.CARDDEMO.EXPORT.DATA.DATA)) -\n"
        "         INDEX (NAME(AWS.M2.CARDDEMO.EXPORT.DATA.INDEX))\n"
    )
    cmds = parse_idcams(text)
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    rc = run_idcams(cmds, (), cat)
    assert rc == 0
    ds = cat.resolve("AWS.M2.CARDDEMO.EXPORT.DATA")
    assert ds.key_length == 4
    assert ds.key_offset == 28
    assert ds.record_size == 500


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_duplicate_dsn_returns_12(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cmds = (
        DefineCluster(name="MY.KSDS", key_length=5, key_offset=0, record_size=80),
        DefineCluster(name="MY.KSDS", key_length=5, key_offset=0, record_size=80),
    )
    rc = run_idcams(cmds, (), cat)
    assert rc == 12
