from pathlib import Path

import pytest
from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition
from jackal.catalog import Allocated, DatasetCatalog, Unallocated
from jackal.dataset import Dataset
from jackal.labels import KsdsLabel, RecordFormat, SequentialLabel
from jackal.model import (
    DD,
    DirectDSN,
    Disp,
    DispAbnormal,
    DispNormal,
    DispStatus,
    TempRef,
)
from jackal.results import AllocationError, Completed
from jackal.system_catalog import NotCataloged, SystemCatalog
from jackal.value_parts import literal
from tests.covers import NotLanguageFeature, covers

FB80 = SequentialLabel(RecordFormat.FB, 80)


def _system(tmp_path: Path) -> SystemCatalog:
    return SystemCatalog(tmp_path / "system")


def _catalog(tmp_path: Path) -> DatasetCatalog:
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    return DatasetCatalog(scratch, _system(tmp_path))


def _upload(tmp_path: Path, dsn: str, data: bytes) -> Dataset:
    source = tmp_path / "upload.dat"
    source.write_bytes(data)
    return _system(tmp_path).add(dsn, source, FB80)


def _given(cat: DatasetCatalog, dd: DD) -> Dataset:
    found = cat.allocate(dd)
    assert isinstance(found, Allocated)
    return found.dataset


def _disposed(cat: DatasetCatalog, dd: DD, ds: Dataset, existed: bool = False) -> None:
    cat.dispose(dd, ds, dd.disposition().resolved(existed), existed, Completed(0))


def _dd(dsn: str, status: DispStatus, normal: DispNormal = DispNormal.KEEP) -> DD:
    return DD(
        ddname="D",
        dsn=DirectDSN(literal(dsn)),
        disp=Disp(status, normal, DispNormal.DELETE),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_new_allocates_empty_file(tmp_path):
    cat = _catalog(tmp_path)
    ds = _given(cat, _dd("J.WORK", DispStatus.NEW))
    assert ds.path.exists() and ds.path.read_bytes() == b""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_dataset_in_the_system_catalog_is_allocated_by_name(tmp_path):
    added = _upload(tmp_path, "J.IN", b"DATA")
    ds = _given(_catalog(tmp_path), _dd("J.IN", DispStatus.SHR))
    assert (ds, added.path.read_bytes()) == (added, b"DATA")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_pass_retains_delete_removes(tmp_path):
    cat = _catalog(tmp_path)
    keep = _given(cat, _dd("J.A", DispStatus.NEW, DispNormal.PASS))
    _disposed(cat, _dd("J.A", DispStatus.NEW, DispNormal.PASS), keep)
    assert keep.path.exists()
    drop = _given(cat, _dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    _disposed(cat, _dd("J.B", DispStatus.NEW, DispNormal.DELETE), drop)
    assert not drop.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_catalogs_a_labelled_ksds_once(tmp_path):
    cat = _catalog(tmp_path)
    ksds = cat.define("A.B.KSDS", KsdsLabel(300, 0, 11))
    assert (ksds.path.exists(), cat.resolve("A.B.KSDS")) == (True, ksds)
    with pytest.raises(ValueError, match="A.B.KSDS"):
        cat.define("A.B.KSDS", KsdsLabel(300, 0, 11))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispose_delete_of_missing_dsn_is_noop(tmp_path):
    _upload(tmp_path, "J.GONE", b"")
    cat = _catalog(tmp_path)
    dd = _dd("J.GONE", DispStatus.SHR, DispNormal.DELETE)
    ds = _given(cat, dd)
    cat.delete_dsn("J.GONE")
    _disposed(cat, dd, ds, existed=True)
    assert cat.resolve("J.GONE") == NotCataloged()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mod_creates_when_absent(tmp_path):
    cat = _catalog(tmp_path)
    ds = _given(cat, _dd("J.MOD", DispStatus.MOD))
    assert ds.path.exists() and ds.path.read_bytes() == b""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_empty_sequential_dataset_reads_end_of_file(tmp_path):
    cat = _catalog(tmp_path)
    dd = DD(
        "D",
        DirectDSN(literal("J.FLAT")),
        Disp(DispStatus.NEW, DispNormal.KEEP, DispAbnormal.DELETE),
    )
    ds = _given(cat, dd)
    assert isinstance(ds, Dataset)
    drv = ds.opened(OpenMode.INPUT)
    result = drv.read_seq()
    drv.close()
    assert result.condition is AccessCondition.END_OF_FILE


def _temp_dd(
    alias: str, status: DispStatus, normal: DispNormal = DispNormal.PASS
) -> DD:
    return DD(
        ddname="W", dsn=TempRef(alias), disp=Disp(status, normal, DispNormal.DELETE)
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_new_allocates_backing_file(tmp_path):
    cat = _catalog(tmp_path)
    ds = _given(cat, _temp_dd("WORKIN", DispStatus.NEW))
    assert ds.path.exists()
    assert ds.path.name == "&&WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_old_resolves_same_dataset(tmp_path):
    cat = _catalog(tmp_path)
    ds1 = _given(cat, _temp_dd("WORKIN", DispStatus.NEW))
    ds2 = _given(cat, _temp_dd("WORKIN", DispStatus.OLD))
    assert ds1.path == ds2.path


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dispose_delete_removes_file(tmp_path):
    cat = _catalog(tmp_path)
    dd = _temp_dd("TEMP", DispStatus.NEW, DispNormal.DELETE)
    ds = _given(cat, dd)
    _disposed(cat, dd, ds)
    assert not ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dispose_pass_retains_file(tmp_path):
    cat = _catalog(tmp_path)
    dd = _temp_dd("TEMP", DispStatus.NEW, DispNormal.PASS)
    ds = _given(cat, dd)
    _disposed(cat, dd, ds)
    assert ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_end_job_deletes_a_surviving_temp(tmp_path):
    cat = _catalog(tmp_path)
    ds = _given(cat, _temp_dd("TEMP", DispStatus.NEW, DispNormal.PASS))
    cat.end_job()
    assert not ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_end_job_is_a_noop_when_every_temp_was_deleted(tmp_path):
    cat = _catalog(tmp_path)
    dd = _temp_dd("TEMP", DispStatus.NEW, DispNormal.DELETE)
    _disposed(cat, dd, _given(cat, dd))
    cat.end_job()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_dd_the_catalog_cannot_allocate_comes_back_with_the_reason(tmp_path):
    cat = _catalog(tmp_path)
    _given(cat, _dd("J.HAVE", DispStatus.NEW, DispNormal.CATLG))
    _given(cat, _temp_dd("TEMP", DispStatus.NEW))
    missing = _dd("J.MISSING", DispStatus.SHR)
    ghost = _temp_dd("GHOST", DispStatus.OLD)
    duplicate = _dd("J.HAVE", DispStatus.NEW)
    duplicate_temp = _temp_dd("TEMP", DispStatus.NEW)
    assert [cat.allocate(d) for d in (missing, ghost, duplicate, duplicate_temp)] == [
        Unallocated(missing, AllocationError.DATASET_NOT_FOUND),
        Unallocated(ghost, AllocationError.TEMP_NOT_CREATED),
        Unallocated(duplicate, AllocationError.DUPLICATE_NAME),
        Unallocated(duplicate_temp, AllocationError.DUPLICATE_NAME),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_unallocated_dd_can_be_given_an_empty_dataset_in_its_place(tmp_path):
    _upload(tmp_path, "J.HAVE", b"OLD")
    cat = _catalog(tmp_path)
    temp = cat.created_empty(_temp_dd("GHOST", DispStatus.OLD))
    direct = cat.created_empty(_dd("J.HAVE", DispStatus.NEW))
    assert (
        temp.path.read_bytes(),
        _given(cat, _temp_dd("GHOST", DispStatus.OLD)),
        direct.path.read_bytes(),
        cat.resolve("J.HAVE"),
    ) == (b"", temp, b"", direct)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_ksds_reads_back_by_key_what_was_written(tmp_path):
    ksds = _catalog(tmp_path).define("MY.KSDS", KsdsLabel(10, 0, 4))
    record = b"KEY DATA  "
    drv = ksds.opened(OpenMode.OUTPUT)
    drv.write(record)
    drv.close()
    drv2 = ksds.opened(OpenMode.INPUT)
    result = drv2.read_key(b"KEY ")
    drv2.close()
    assert result.condition is AccessCondition.OK
    assert result.data == record


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_temp_and_a_dataset_of_the_same_name_are_separate_datasets(tmp_path):
    cat = _catalog(tmp_path)
    temp = DD(
        ddname="T",
        dsn=TempRef("EXTR"),
        disp=Disp(DispStatus.NEW, DispNormal.PASS, DispAbnormal.DELETE),
    )
    named = _dd("EXTR", DispStatus.NEW)
    t, n = _given(cat, temp), _given(cat, named)
    assert isinstance(t, Dataset) and isinstance(n, Dataset)
    paths_differ = t.path != n.path
    cat.end_job()
    assert (paths_differ, t.path.exists(), n.path.exists()) == (True, False, True)
