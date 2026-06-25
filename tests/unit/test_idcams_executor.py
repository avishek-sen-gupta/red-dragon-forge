"""Tests for the IDCAMS executor."""

from __future__ import annotations

from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.idcams.commands import DefineCluster, Delete, IfMaxcc, Repro
from jackal.model import DD, Disp, DispNormal, DispStatus
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
        DD("INF", "IN.PS", Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)),
        DD("OUT", "OUT.KSDS", Disp(DispStatus.OLD, DispNormal.KEEP, DispNormal.KEEP)),
    )
    cmds = (
        DefineCluster(name="OUT.KSDS", key_length=3, key_offset=0, record_size=9),
        Repro(infile_dd="INF", outfile_dd="OUT"),
    )
    rc = run_idcams(cmds, dds, cat)
    assert rc == 0
    # read OUT.KSDS back via the IndexedDriver and confirm BBB record present
    from interpreter.cobol.file_drivers import IndexedDriver
    from interpreter.cobol.file_enums import OpenMode

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
