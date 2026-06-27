from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog, DatasetSpec
from jackal.dsn import DirectDSN, TempRef
from jackal.model import DD, Disp, DispNormal, DispStatus, DatasetOrg
from tests.covers import covers, NotLanguageFeature


def _dd(dsn: str, status: DispStatus, normal: DispNormal = DispNormal.KEEP) -> DD:
    return DD(
        ddname="D", dsn=DirectDSN(dsn), disp=Disp(status, normal, DispNormal.DELETE)
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_new_allocates_empty_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate(_dd("J.WORK", DispStatus.NEW))
    assert ds.path.exists() and ds.path.read_bytes() == b""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_then_shr_resolves_same_file(tmp_path):
    src = tmp_path / "seed.dat"
    src.write_bytes(b"DATA")
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cat.seed("J.IN", src)
    ds = cat.allocate(_dd("J.IN", DispStatus.SHR))
    assert ds.path == src


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_pass_retains_delete_removes(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    keep = cat.allocate(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    cat.dispose(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    assert keep.path.exists()
    drop = cat.allocate(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    cat.dispose(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    assert not drop.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_shr_on_unknown_dsn_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    with pytest.raises(KeyError):
        cat.allocate(_dd("J.MISSING", DispStatus.SHR))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_shr_resolves_from_data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "A.B.PS").write_bytes(b"REC1")
    wd = tmp_path / "wd"
    wd.mkdir()
    cat = DatasetCatalog(workdir=wd, data_dir=data)
    dd = DD(
        "D", DirectDSN("A.B.PS"), Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)
    )
    assert cat.allocate(dd).path == data / "A.B.PS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_ksds(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(
        dsn="A.B.KSDS",
        org=DatasetOrg.KSDS,
        key_offset=0,
        key_length=11,
        record_size=300,
    )
    ds = cat.allocate_new(spec)
    assert ds.org is DatasetOrg.KSDS and ds.key_length == 11 and ds.record_size == 300
    assert ds.path.exists()
    assert cat.resolve("A.B.KSDS").org is DatasetOrg.KSDS


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_duplicate_dsn_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(
        dsn="A.B.KSDS",
        org=DatasetOrg.KSDS,
        key_offset=0,
        key_length=11,
        record_size=300,
    )
    cat.allocate_new(spec)
    with pytest.raises(ValueError, match="A.B.KSDS"):
        cat.allocate_new(spec)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_ksds_zero_record_size_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(
        dsn="A.B.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=11, record_size=0
    )
    with pytest.raises(ValueError, match="record_size"):
        cat.allocate_new(spec)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_ksds_zero_key_length_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(
        dsn="A.B.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=0, record_size=300
    )
    with pytest.raises(ValueError, match="key_length"):
        cat.allocate_new(spec)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispose_delete_of_missing_dsn_is_noop(tmp_path):
    # DISP=(...,DELETE) on a DSN that was never allocated must not raise.
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cat.dispose(_dd("J.NEVER", DispStatus.SHR, DispNormal.DELETE))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mod_creates_when_absent(tmp_path):
    # MOD on a DSN absent from catalog + data_dir creates an empty backing file.
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate(_dd("J.MOD", DispStatus.MOD))
    assert ds.path.exists() and ds.path.read_bytes() == b""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_dataset_ps_empty_returns_eof(tmp_path):
    from interpreter.cobol.access_result import AccessCondition
    from interpreter.cobol.file_enums import OpenMode

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = DD(
        "D",
        DirectDSN("J.FLAT"),
        Disp(DispStatus.NEW, DispNormal.KEEP, DispNormal.DELETE),
    )
    cat.allocate(dd)
    drv = cat.open_dataset("J.FLAT", OpenMode.INPUT, record_size=80)
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
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate(_temp_dd("&&WORKIN", DispStatus.NEW))
    assert ds.path.exists()
    assert ds.path.name == "WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_old_resolves_same_dataset(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds1 = cat.allocate(_temp_dd("&&WORKIN", DispStatus.NEW))
    ds2 = cat.allocate(_temp_dd("&&WORKIN", DispStatus.OLD))
    assert ds1.path == ds2.path


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_old_unregistered_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    with pytest.raises(KeyError):
        cat.allocate(_temp_dd("&&GHOST", DispStatus.OLD))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dispose_delete_removes_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = _temp_dd("&&TEMP", DispStatus.NEW, DispNormal.DELETE)
    ds = cat.allocate(dd)
    cat.dispose(dd)
    assert not ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dispose_pass_retains_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = _temp_dd("&&TEMP", DispStatus.NEW, DispNormal.PASS)
    ds = cat.allocate(dd)
    cat.dispose(dd)
    assert ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cleanup_temps_deletes_surviving_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate(_temp_dd("&&TEMP", DispStatus.NEW, DispNormal.PASS))
    cat.cleanup_temps()
    assert not ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cleanup_temps_noop_when_all_deleted(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = _temp_dd("&&TEMP", DispStatus.NEW, DispNormal.DELETE)
    cat.allocate(dd)
    cat.dispose(dd)
    cat.cleanup_temps()  # must not raise


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_new_duplicate_alias_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cat.allocate(_temp_dd("&&TEMP", DispStatus.NEW))
    with pytest.raises(ValueError, match="&&TEMP"):
        cat.allocate(_temp_dd("&&TEMP", DispStatus.NEW))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_dataset_ksds_write_then_read(tmp_path):
    from interpreter.cobol.access_result import AccessCondition
    from interpreter.cobol.file_enums import OpenMode

    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(
        dsn="MY.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=4, record_size=10
    )
    cat.allocate_new(spec)
    record = b"KEY DATA  "  # 10 bytes; key = first 4
    drv = cat.open_dataset("MY.KSDS", OpenMode.OUTPUT)
    drv.write(record)
    drv.close()
    drv2 = cat.open_dataset("MY.KSDS", OpenMode.INPUT)
    result = drv2.read_key(b"KEY ")
    drv2.close()
    assert result.condition is AccessCondition.OK
    assert result.data == record
